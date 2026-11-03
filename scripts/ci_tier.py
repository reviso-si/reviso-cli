#!/usr/bin/env python3
"""Tiered CI runner: BVT/full tiers, per-stage budgets, content-addressed receipts.

Behavior is defined by scripts/ci_tier.json next to this file:

    {
      "default_tier": "quick",
      "tiers": {"quick": ["unit"], "full": ["unit", "integration"]},
      "stages": {
        "unit": {
          "command": ["python3", "-m", "pytest", "tests/unit", "-q"],
          "cwd": ".",
          "budget": 900,
          "watch": ["src/**/*.py", "tests/unit/**/*.py"],
          "lane": "backend"
        }
      },
      "max_parallel_lanes": 2,
      "keep_runs": 10
    }

A stage that passed is skipped on later runs while the hash of its watched
inputs and its command are unchanged. --no-cache forces a rerun. --retry-failed
reruns only the stages that did not pass in the most recent run, ignoring their
receipts; stages that did pass are still skipped when their receipts hold.

Stages on different lanes run concurrently; same-lane stages run in order.
A lane failure cancels not-yet-started stages everywhere. Every stage gets its
own process group and a hard budget: SIGTERM, short grace, then SIGKILL.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

CI_TIER_VERSION = 1
TERMINATION_GRACE_SECONDS = 5.0
STATUS_PASS, STATUS_FAIL, STATUS_TIMEOUT = "pass", "fail", "timeout"
STATUS_CANCELLED, STATUS_INTERRUPTED = "cancelled", "interrupted"
UNSET = object()

_GLOB_CACHE: dict[str, re.Pattern] = {}


def _glob_regex(pattern: str) -> re.Pattern:
    """Compile a glob with ** support; full_match needs Python 3.13."""
    cached = _GLOB_CACHE.get(pattern)
    if cached is not None:
        return cached
    out, index, length = [], 0, len(pattern)
    while index < length:
        char = pattern[index]
        if char == '*':
            if pattern[index:index + 3] == '**/':
                out.append('(?:[^/]+/)*')
                index += 3
                continue
            if pattern[index:index + 2] == '**':
                out.append('.*')
                index += 2
                continue
            out.append('[^/]*')
            index += 1
        elif char == '?':
            out.append('[^/]')
            index += 1
        else:
            out.append(re.escape(char))
            index += 1
    cached = re.compile('^(?:' + ''.join(out) + ')$')
    _GLOB_CACHE[pattern] = cached
    return cached


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def state_dir(root: Path) -> Path:
    return root / ".ci-state" / "ci-tier"


def load_config(root: Path) -> dict:
    path = root / "scripts" / "ci_tier.json"
    config = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(config.get("stages"), dict) or not config["stages"]:
        raise ValueError("ci_tier.json must define a non-empty stages object")
    if not isinstance(config.get("tiers"), dict) or not config["tiers"]:
        raise ValueError("ci_tier.json must define a non-empty tiers object")
    for tier, names in config["tiers"].items():
        unknown = [n for n in names if n not in config["stages"]]
        if unknown:
            raise ValueError(f"tier {tier} references unknown stages: {unknown}")
    return config


def resolve_tier(config: dict, requested: str | None) -> tuple[str, list[str]]:
    tier = requested or config.get("default_tier")
    if tier not in config["tiers"]:
        raise ValueError(f"unknown tier {tier!r}; available: {sorted(config['tiers'])}")
    return tier, list(config["tiers"][tier])


def stage_config(config: dict, name: str) -> dict:
    stage = config["stages"][name]
    for key in ("command",):
        if not isinstance(stage.get(key), list) or not stage[key]:
            raise ValueError(f"stage {name} needs a non-empty command list")
    return stage


def _exclude_forms(exclude: list[str] | None) -> list[str]:
    """Dir-pruning forms: a pattern matches dirs directly and via its tree root."""
    forms: list[str] = []
    for pattern in exclude or []:
        base = pattern[:-3] if pattern.endswith("/**") else pattern
        forms.extend({pattern, base, base + "/**"})
    return forms


PRUNE_ALWAYS = {".git", ".ci-state", "node_modules", ".venv", "__pycache__",
                ".pytest_cache", "htmlcov"}


def input_hash(root: Path, stage: dict) -> str:
    """Content hash of the files a stage depends on; empty watch = uncacheable.

    Walks the tree once, pruning dependency/state directories during traversal
    so a fresh node_modules or .venv cannot dominate the hash latency.
    """
    patterns = stage.get("watch") or []
    if not patterns:
        return "uncacheable"
    dir_forms = _exclude_forms(stage.get("exclude") or [])
    files: set[Path] = set()
    for dirpath, dirnames, filenames in os.walk(root):
        rel = Path(dirpath).relative_to(root)
        kept = []
        for name in dirnames:
            child = (rel / name).as_posix()
            if name in PRUNE_ALWAYS or any(_glob_regex(form).match(child) for form in dir_forms):
                continue
            kept.append(name)
        dirnames[:] = kept
        for name in filenames:
            child = (rel / name).as_posix()
            if any(_glob_regex(form).match(child) for form in dir_forms):
                continue
            if any(_glob_regex(pattern).match(child) for pattern in patterns):
                files.add(rel / name)
    if not files:
        return "uncacheable"
    digest = hashlib.sha256()
    for rel in sorted(files, key=lambda p: p.as_posix()):
        digest.update(rel.as_posix().encode())
        digest.update(b"\0")
        with (root / rel).open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()


def read_receipts(root: Path) -> dict:
    path = state_dir(root) / "receipts.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_receipt(root: Path, name: str, stage: dict, digest: str, duration: float) -> None:
    receipts = read_receipts(root)
    receipts[name] = {"version": CI_TIER_VERSION, "command": stage["command"],
                      "input": digest, "ended_at": datetime.datetime.now(
                          datetime.timezone.utc).isoformat(), "duration": duration}
    path = state_dir(root) / "receipts.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(receipts, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def receipt_hit(root: Path, name: str, stage: dict, digest: str, cache: bool) -> bool:
    if not cache or digest == "uncacheable":
        return False
    stored = read_receipts(root).get(name)
    return bool(stored and stored.get("version") == CI_TIER_VERSION
                and stored.get("command") == stage["command"] and stored.get("input") == digest)


def terminate_group(process: subprocess.Popen) -> None:
    if sys.platform == "win32":
        process.terminate()
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass
    deadline = time.monotonic() + TERMINATION_GRACE_SECONDS
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return
        time.sleep(0.05)
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    process.wait()


def run_stage(root: Path, name: str, stage: dict, log_path: Path,
              cancel: threading.Event) -> dict:
    started = time.monotonic()
    result = {"name": name, "status": STATUS_FAIL, "exit": None, "duration": 0.0,
              "budget": stage.get("budget"), "log": str(log_path)}
    cwd = root / stage.get("cwd", ".")
    with log_path.open("w", encoding="utf-8") as log:
        log.write(f"$ (cd {stage.get('cwd', '.')}) {' '.join(stage['command'])}\n")
        log.flush()
        try:
            process = subprocess.Popen(stage["command"], cwd=cwd, stdout=log,
                                       stderr=subprocess.STDOUT, text=True,
                                       start_new_session=sys.platform != "win32")
        except OSError as error:
            log.write(f"ci-tier: cannot start stage: {error}\n")
            result["duration"] = time.monotonic() - started
            return result
        budget = stage.get("budget")
        deadline = time.monotonic() + budget if budget else None
        while True:
            code = process.poll()
            if code is not None:
                result["exit"], result["status"] = code, STATUS_PASS if code == 0 else STATUS_FAIL
                break
            if cancel.is_set():
                terminate_group(process)
                result["status"] = STATUS_INTERRUPTED
                break
            if deadline is not None and time.monotonic() >= deadline:
                terminate_group(process)
                result["status"], result["exit"] = STATUS_TIMEOUT, 124
                break
            time.sleep(0.05)
    result["duration"] = time.monotonic() - started
    return result


def run_lane(root: Path, lane_stages: list[tuple[str, dict]], run_dir: Path,
             plan: dict, cancel: threading.Event, cache: bool) -> list[dict]:
    results = []
    for name, stage in lane_stages:
        if cancel.is_set():
            results.append({"name": name, "status": STATUS_CANCELLED, "exit": None,
                            "duration": 0.0, "budget": stage.get("budget"), "log": ""})
            continue
        digest = plan[name]["digest"]
        if plan[name]["use_receipt"] and receipt_hit(root, name, stage, digest, cache):
            print(f"[ci-tier] CACHED {name}", flush=True)
            results.append({"name": name, "status": STATUS_PASS, "exit": 0, "duration": 0.0,
                            "budget": stage.get("budget"), "receipt": True, "log": ""})
            continue
        print(f"[ci-tier] START {name}", flush=True)
        result = run_stage(root, name, stage, run_dir / "logs" / f"{name}.log", cancel)
        result.setdefault("receipt", False)
        if result["status"] == STATUS_PASS:
            write_receipt(root, name, stage, digest, result["duration"])
            print(f"[ci-tier] PASS {name} ({result['duration']:.1f}s)", flush=True)
        else:
            cancel.set()
            print(f"[ci-tier] {result['status'].upper()} {name} "
                  f"({result['duration']:.1f}s)", flush=True)
            tail_log(run_dir / "logs" / f"{name}.log")
        results.append(result)
    return results


def tail_log(path: Path, lines: int = 40) -> None:
    try:
        content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return
    for line in content[-lines:]:
        print(f"[ci-tier]   {line}", flush=True)


def plan_run(config: dict, tier: str, names: list[str], retry: bool, root: Path) -> dict:
    previous = {}
    if retry:
        last = state_dir(root) / "last-run.json"
        try:
            previous = {s["name"]: s["status"] for s in
                        json.loads(last.read_text(encoding="utf-8")).get("stages", [])}
        except (OSError, ValueError):
            previous = {}
    plan = {}
    for name in names:
        stage = stage_config(config, name)
        digest = input_hash(root, stage)
        forced = retry and previous.get(name) != STATUS_PASS
        plan[name] = {"stage": stage, "digest": digest, "use_receipt": not forced}
    return plan


def execute(root: Path, config: dict, tier: str, names: list[str],
            cache: bool, retry: bool) -> tuple[int, dict]:
    plan = plan_run(config, tier, names, retry, root)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = state_dir(root) / "runs" / f"{stamp}-{os.getpid()}"
    (run_dir / "logs").mkdir(parents=True, exist_ok=True)
    cancel = threading.Event()
    interrupted = threading.Event()
    previous_signals = {}

    def interrupt(signum, _frame):
        cancel.set()
        interrupted.set()
        raise KeyboardInterrupt

    for sig in (signal.SIGINT, getattr(signal, "SIGTERM", None)):
        if sig is None:
            continue
        try:
            previous_signals[sig] = signal.signal(sig, interrupt)
        except (ValueError, OSError):
            pass
    lanes: dict[str, list[tuple[str, dict]]] = {}
    for name in names:
        stage = stage_config(config, name)
        lanes.setdefault(stage.get("lane") or f"stage-{name}", []).append((name, stage))
    workers = max(1, min(int(config.get("max_parallel_lanes", 1)), len(lanes)))
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(run_lane, root, stages, run_dir, plan, cancel, cache)
                       for stages in lanes.values()]
            results = [item for future in futures for item in future.result()]
    except KeyboardInterrupt:
        results = []
        deadline = time.monotonic() + 10
        while any(future.running() for future in futures) and time.monotonic() < deadline:
            time.sleep(0.05)
    finally:
        for sig, handler in previous_signals.items():
            signal.signal(sig, handler)
    order = {name: index for index, name in enumerate(names)}
    results.sort(key=lambda item: order.get(item["name"], 0))
    summary = {"run_id": run_dir.name, "tier": tier, "version": CI_TIER_VERSION,
               "started_at": stamp,
               "ended_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
               "stages": results}
    (state_dir(root) / "last-run.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (run_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    prune_runs(root, int(config.get("keep_runs", 10)))
    codes = {STATUS_FAIL: 1, STATUS_TIMEOUT: 124, STATUS_INTERRUPTED: 130}
    exit_code = max((codes.get(item["status"], 0) for item in results), default=0)
    if interrupted.is_set():
        exit_code = max(exit_code, 130)
    return exit_code, summary


def prune_runs(root: Path, keep: int) -> None:
    runs = state_dir(root) / "runs"
    if not runs.is_dir():
        return
    for stale in sorted(runs.iterdir(), key=lambda p: p.name)[:-keep] if keep > 0 else []:
        if stale.is_dir():
            for child in sorted(stale.rglob("*"), reverse=True):
                if child.is_file():
                    child.unlink(missing_ok=True)
            for child in sorted(stale.rglob("*"), reverse=True):
                if child.is_dir():
                    child.rmdir()
            stale.rmdir()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tier", help="tier from ci_tier.json (default: default_tier)")
    parser.add_argument("--stage", action="append", dest="stages",
                        help="run only these stages (repeatable)")
    parser.add_argument("--retry-failed", action="store_true",
                        help="rerun stages that did not pass in the last run")
    parser.add_argument("--no-cache", action="store_true", help="ignore green receipts")
    parser.add_argument("--list", action="store_true", help="print tiers and stages")
    args = parser.parse_args(argv)
    root = repo_root()
    try:
        config = load_config(root)
        tier, names = resolve_tier(config, args.tier)
        if args.stages:
            unknown = [s for s in args.stages if s not in config["stages"]]
            if unknown:
                raise ValueError(f"unknown stages: {unknown}")
            names = args.stages
    except ValueError as error:
        print(f"ci-tier: {error}", file=sys.stderr)
        return 2
    if args.list:
        for tier_name, tier_stages in config["tiers"].items():
            print(f"{tier_name}: {', '.join(tier_stages)}")
        return 0
    cache = not args.no_cache and not os.environ.get("CI_TIER_NO_CACHE")
    exit_code, summary = execute(root, config, tier, names, cache, args.retry_failed)
    failed = [item["name"] for item in summary["stages"]
              if item["status"] not in (STATUS_PASS, STATUS_CANCELLED)]
    if failed:
        print(f"[ci-tier] rerun failed stages: python3 scripts/ci_tier.py "
              f"--tier {tier} --retry-failed", flush=True)
        return exit_code
    print(f"[ci-tier] tier {tier}: all stages passed", flush=True)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
