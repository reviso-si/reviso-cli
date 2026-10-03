"""Local command journal — stable operation_id across CLI command reruns (P1c).

The CLI is the client that mints ``operation_id``. Design v3 requires that id to
be REUSED across retries of ONE logical operation, so a crashed-then-rerun
command (network died after the server committed but before the response landed)
replays instead of double-creating.

A fresh ``make_id("op")`` per process cannot satisfy that. Instead we persist an
entry keyed by a fingerprint of the command's USER-SUPPLIED inputs under
``command_journal.json`` in the local state directory. Each entry is an object::

    {"operation_id": "op_...", "request": {"base_version_id": "ver_1"}}

so a rerun recovers BOTH the id and the exact resolved request the first run
committed with. This matters for update: the base version is resolved from a
dynamic "latest" query, so it must NOT be part of the key (a rerun would see the
newly-committed version and drift), and the concrete base the first run used must
be replayed verbatim -- otherwise the retry commits a fresh version instead of
replaying.

Entries are pruned once the caller confirms a clean commit via ``forget`` so the
journal does not grow without bound; a still-present entry means "this operation
may not have durably committed -- reuse it on retry."

Concurrency: two processes running the same command must agree on ONE entry, and
two different commands must not clobber each other's entry. Every read-mutate-
write runs under an exclusive ``flock`` on a sidecar lock file, and the journal
is rewritten atomically via a temp file + ``os.replace`` so a crash mid-write
never leaves a truncated map. A corrupt journal FAILS CLOSED: silently treating
it as empty would mint a new id and risk a double-commit.
"""
from __future__ import annotations

import fcntl
import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Callable

from .ids import make_id, sha256_text
from .paths import local_dir

_SEP = "\x1f"
_JOURNAL = "command_journal.json"
_LOCK = "command_journal.lock"


class CommandJournalError(RuntimeError):
    """Raised when the idempotency journal is unreadable and must be repaired."""


def _journal_path() -> Path:
    return local_dir() / _JOURNAL


@contextmanager
def _locked():
    base = local_dir()
    base.mkdir(parents=True, exist_ok=True)
    lock_path = base / _LOCK
    with open(lock_path, "w") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _load() -> dict:
    path = _journal_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except (ValueError, OSError) as exc:
        # Fail closed: a corrupt idempotency journal must not be treated as
        # empty, or we would mint a fresh id and risk double-committing an
        # operation that already committed. Force the user to fix/confirm.
        raise CommandJournalError(
            f"command journal at {path} is unreadable ({exc}); "
            "resolve it before retrying an idempotent write") from exc
    if not isinstance(data, dict):
        raise CommandJournalError(
            f"command journal at {path} is not an object; repair it")
    return data


def _atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    os.replace(tmp, path)


def fingerprint(command: str, parts: list[str]) -> str:
    """Stable key over the command's identity-bearing USER inputs."""
    return sha256_text(_SEP.join([command, *[str(p) for p in parts]]))


def reserve(command: str, parts: list[str],
            resolve: Callable[[], dict] | None = None) -> dict:
    """Return the persisted entry for this command identity, minting once.

    On the first call for a fingerprint, ``resolve()`` (if given) is invoked to
    compute the request payload the id will commit with (e.g. the resolved base
    version); the entry ``{operation_id, request}`` is then persisted. Later
    calls with the same fingerprint replay that same entry verbatim.

    ``resolve`` runs OUTSIDE the lock (it may do network I/O). A double-checked
    insert under the lock guarantees a single winning entry even if concurrent
    racers each resolved their own request -- the losers' work is discarded.
    """
    fp = fingerprint(command, parts)
    with _locked():
        existing = _load().get(fp)
        if isinstance(existing, dict) and existing.get("operation_id"):
            return existing
    request = dict(resolve() if resolve else {})
    entry = {"operation_id": make_id("op"), "request": request}
    with _locked():
        journal = _load()
        winner = journal.get(fp)
        if isinstance(winner, dict) and winner.get("operation_id"):
            return winner  # a concurrent racer already committed the entry
        journal[fp] = entry
        _atomic_write(_journal_path(), journal)
        return entry


def operation_id_for(command: str, parts: list[str]) -> str:
    """Convenience for commands with no resolved request (e.g. publish)."""
    return reserve(command, parts)["operation_id"]


def forget(command: str, parts: list[str]) -> None:
    """Drop the journal entry after a confirmed clean commit."""
    fp = fingerprint(command, parts)
    with _locked():
        journal = _load()
        if journal.pop(fp, None) is not None:
            _atomic_write(_journal_path(), journal)
