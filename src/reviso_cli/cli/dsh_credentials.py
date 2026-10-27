"""Read Reviso refs from the DSH host credential file.

The DSH host stores its Reviso connection as refs in
$DSH_HOME/.credentials.yaml (fallback ~/.dsh), under a top-level refs
mapping. This module is a read-only last-resort source for the CLI: the
host owns the file and its real YAML shape, so anything unreadable,
unsafe, or unexpected yields an empty result and the CLI fails as it did
before.
"""
import math
import os
import stat
import sys
import time
from pathlib import Path

TOKEN_REF = "REVISO_DSH_TOKEN"
WORKSPACE_REF = "REVISO_DSH_WORKSPACE_ID"
SERVER_REF = "REVISO_DSH_SERVER"
EXPIRES_REF = "REVISO_DSH_EXPIRES_AT"

# The DSH host's own reader rejects credential files outside this range; the
# CLI mirrors that rather than trusting a borderline file.
CREDENTIAL_FILE_LIMIT_BYTES = 1024 * 1024
_MAX_EXPIRES_MS = 253402300799999  # 9999-12-31T23:59:59.999Z, keeps dates storable

_warned_paths: set[str] = set()


def dsh_credential_path() -> Path:
    # Same directory resolution as the DSH host tooling.
    home = os.environ.get("DSH_HOME") or Path.home() / ".dsh"
    return Path(home) / ".credentials.yaml"


def read_dsh_refs(path: Path | None = None) -> dict[str, str]:
    """Return the flat `REF: value` entries directly under the refs mapping."""
    target = path or dsh_credential_path()
    try:
        info = target.stat()
        issue = _private_file_issue(info)
        if issue:
            _warn_unsafe(target, issue)
            return {}
        text = target.read_text()
    except OSError:
        return {}
    refs: dict[str, str] = {}
    in_refs = False
    refs_indent = -1
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        key, sep, value = stripped.partition(":")
        if not sep:
            continue
        if indent == 0:
            in_refs = key.strip() == "refs" and not value.strip()
            refs_indent = -1
        elif in_refs:
            if refs_indent < 0:
                refs_indent = indent
            if indent == refs_indent:
                refs[key.strip()] = _scalar(value)
    return refs


def _private_file_issue(info: os.stat_result) -> str:
    """Mirror the DSH host's readPrivateCredentialFile sanity checks."""
    if not stat.S_ISREG(info.st_mode):
        return "not a regular file"
    if not 0 < info.st_size <= CREDENTIAL_FILE_LIMIT_BYTES:
        return "file size is outside the accepted range"
    if hasattr(os, "getuid") and info.st_uid != os.getuid():
        return "file is owned by another user"
    if os.name != "nt" and info.st_mode & 0o077:
        return "file permissions must be 0600 or stricter"
    return ""


def _warn_unsafe(path: Path, issue: str) -> None:
    # One CLI run reads this file several times (server, token, workspace);
    # warn once per file so the noise stays a single line.
    key = str(path)
    if key not in _warned_paths:
        _warned_paths.add(key)
        print(f"reviso: ignoring DSH host credential file {path}: {issue}",
              file=sys.stderr)


def dsh_expires_at(refs: dict[str, str]) -> float | None:
    """Epoch seconds for the recorded expiry, or None when absent/malformed.

    The host records epoch milliseconds and its YAML writer may quote the
    number; anything it could not have written is treated as absent.
    """
    raw = refs.get(EXPIRES_REF, "").strip().strip("'\"")
    try:
        value = float(raw)
    except ValueError:
        return None
    if not math.isfinite(value) or not 0 < value <= _MAX_EXPIRES_MS:
        return None
    return value / 1000


def dsh_token_expired(refs: dict[str, str], now: float | None = None) -> bool:
    """True when the refs carry a parseable expiry already in the past."""
    expires = dsh_expires_at(refs)
    if expires is None:
        return False
    return (time.time() if now is None else now) >= expires


def dsh_workspace() -> str:
    return read_dsh_refs().get(WORKSPACE_REF, "")


def _scalar(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        return value[1:-1]
    return value
