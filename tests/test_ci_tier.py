"""Engine tests for scripts/ci_tier.py: budgets, receipts, lanes, retry."""
from __future__ import annotations

import importlib.util
import json
import sys
import time
from pathlib import Path

ENGINE_SOURCE = Path(__file__).resolve().parent.parent / "scripts" / "ci_tier.py"


def load_engine(root: Path):
    spec = importlib.util.spec_from_file_location("ci_tier_under_test",
                                                  root / "scripts" / "ci_tier.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_repo(tmp_path: Path, config: dict):
    (tmp_path / "scripts").mkdir(exist_ok=True)
    (tmp_path / "scripts" / "ci_tier.json").write_text(json.dumps(config), encoding="utf-8")
    (tmp_path / "scripts" / "ci_tier.py").write_text(
        ENGINE_SOURCE.read_text(encoding="utf-8"), encoding="utf-8")
    return tmp_path, load_engine(tmp_path)


COUNTER_STAGE = {
    "command": [sys.executable, "-c",
                "from pathlib import Path\np = Path('counter.txt')\n"
                "p.write_text((p.read_text() if p.exists() else '') + 'x')\n"
                "print('counter ran')"],
    "cwd": ".", "budget": 120, "watch": ["input.txt"], "lane": "one",
}


def test_receipt_skips_until_inputs_change(tmp_path):
    root, engine = make_repo(tmp_path, {
        "default_tier": "quick", "tiers": {"quick": ["count"]}, "stages": {"count": COUNTER_STAGE},
    })
    (root / "input.txt").write_text("v1", encoding="utf-8")
    assert engine.main(["--tier", "quick"]) == 0
    assert (root / "counter.txt").read_text() == "x"
    assert engine.main(["--tier", "quick"]) == 0
    assert (root / "counter.txt").read_text() == "x", "receipt must skip the second run"
    (root / "input.txt").write_text("v2", encoding="utf-8")
    assert engine.main(["--tier", "quick"]) == 0
    assert (root / "counter.txt").read_text() == "xx", "changed inputs must invalidate"
    assert engine.main(["--tier", "quick", "--no-cache"]) == 0
    assert (root / "counter.txt").read_text() == "xxx", "--no-cache forces a rerun"


def test_budget_timeout_kills_stage(tmp_path):
    root, engine = make_repo(tmp_path, {
        "default_tier": "quick",
        "tiers": {"quick": ["slow"]},
        "stages": {"slow": {"command": [sys.executable, "-c", "import time; time.sleep(60)"],
                            "cwd": ".", "budget": 1, "watch": [], "lane": "one"}},
    })
    started = time.monotonic()
    code = engine.main(["--tier", "quick"])
    elapsed = time.monotonic() - started
    assert code == 124
    assert elapsed < 30, f"budget termination took {elapsed:.1f}s"
    summary = json.loads((root / ".ci-state" / "ci-tier" / "last-run.json").read_text())
    assert summary["stages"][0]["status"] == "timeout"


def test_retry_failed_reruns_only_failures(tmp_path):
    fail_stage = {"command": [sys.executable, "-c", "raise SystemExit(3)"],
                  "cwd": ".", "budget": 60, "watch": ["good.input"], "lane": "one"}
    ok_stage = {"command": [sys.executable, "-c", "print('ok')"],
                "cwd": ".", "budget": 60, "watch": ["good.input"], "lane": "two"}
    root, engine = make_repo(tmp_path, {
        "default_tier": "quick", "tiers": {"quick": ["bad", "good"]},
        "stages": {"bad": fail_stage, "good": ok_stage}, "max_parallel_lanes": 2,
    })
    (root / "good.input").write_text("stable", encoding="utf-8")
    assert engine.main(["--tier", "quick"]) == 1
    first = json.loads((root / ".ci-state" / "ci-tier" / "last-run.json").read_text())
    first_by_name = {item["name"]: item for item in first["stages"]}
    assert first_by_name["good"]["status"] == "pass", "good must pass before bad fails"
    (root / "scripts" / "ci_tier.json").write_text(json.dumps({
        "default_tier": "quick", "tiers": {"quick": ["bad", "good"]},
        "stages": {"bad": ok_stage, "good": ok_stage}, "max_parallel_lanes": 2,
    }), encoding="utf-8")
    assert engine.main(["--tier", "quick", "--retry-failed"]) == 0
    summary = json.loads((root / ".ci-state" / "ci-tier" / "last-run.json").read_text())
    by_name = {item["name"]: item for item in summary["stages"]}
    assert by_name["bad"]["status"] == "pass"
    assert by_name["good"].get("receipt") is True, "passed stage must stay receipt-cached"


def test_cancellation_stops_running_and_pending_stages(tmp_path):
    fast_fail = {"command": [sys.executable, "-c", "raise SystemExit(3)"],
                 "cwd": ".", "budget": 60, "watch": [], "lane": "one"}
    pending = {"command": [sys.executable, "-c", "print('never')"],
               "cwd": ".", "budget": 60, "watch": [], "lane": "one"}
    running = {"command": [sys.executable, "-c", "import time; time.sleep(30)"],
               "cwd": ".", "budget": 60, "watch": [], "lane": "two"}
    root, engine = make_repo(tmp_path, {
        "default_tier": "quick", "tiers": {"quick": ["fastfail", "pending", "running"]},
        "stages": {"fastfail": fast_fail, "pending": pending, "running": running},
        "max_parallel_lanes": 2,
    })
    assert engine.main(["--tier", "quick"]) == 130
    summary = json.loads((root / ".ci-state" / "ci-tier" / "last-run.json").read_text())
    by_name = {item["name"]: item for item in summary["stages"]}
    assert by_name["fastfail"]["status"] == "fail"
    assert by_name["pending"]["status"] == "cancelled", "same-lane stage must not start"
    assert by_name["running"]["status"] == "interrupted", "running stage must be terminated"


def test_exclude_keeps_dependency_noise_out_of_receipts(tmp_path):
    stage = {"command": [sys.executable, "-c", "print('build')"],
             "cwd": ".", "budget": 60, "watch": ["src/**"],
             "exclude": ["src/vendor/**"], "lane": "one"}
    root, engine = make_repo(tmp_path, {
        "default_tier": "quick", "tiers": {"quick": ["build"]}, "stages": {"build": stage},
    })
    (root / "src").mkdir()
    (root / "src" / "app.py").write_text("print('v1')", encoding="utf-8")
    (root / "src" / "vendor").mkdir()
    (root / "src" / "vendor" / "dep.py").write_text("v1", encoding="utf-8")
    assert engine.main(["--tier", "quick"]) == 0
    assert engine.main(["--tier", "quick"]) == 0, "unchanged inputs must be cached"
    (root / "src" / "vendor" / "dep.py").write_text("v2", encoding="utf-8")
    assert engine.main(["--tier", "quick"]) == 0, "excluded paths must not invalidate"
    (root / "src" / "app.py").write_text("print('v2')", encoding="utf-8")
    assert engine.main(["--tier", "quick"]) == 0


def test_invalid_config_and_unknown_tier(tmp_path):
    root, engine = make_repo(tmp_path, {"default_tier": "quick", "tiers": {"quick": ["missing"]},
                                "stages": {}})
    assert engine.main([]) == 2
    (root / "scripts" / "ci_tier.json").write_text(json.dumps({
        "default_tier": "nope", "tiers": {"quick": []},
        "stages": {"a": {"command": ["true"], "cwd": "."}}}), encoding="utf-8")
    assert engine.main([]) == 2
