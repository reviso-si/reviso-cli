"""Read Reviso refs from the DSH host credential file.

The DSH host stores its Reviso connection as refs in
$DSH_HOME/.credentials.yaml (fallback ~/.dsh), under a top-level refs
mapping. This module is a read-only last-resort source for the CLI: the
host owns the file and its real YAML shape, so anything unreadable or
unexpected yields an empty result and the CLI fails as it did before.
"""
import os
from pathlib import Path

TOKEN_REF = "REVISO_DSH_TOKEN"
WORKSPACE_REF = "REVISO_DSH_WORKSPACE_ID"
SERVER_REF = "REVISO_DSH_SERVER"


def dsh_credential_path() -> Path:
    # Same directory resolution as the DSH host tooling.
    home = os.environ.get("DSH_HOME") or Path.home() / ".dsh"
    return Path(home) / ".credentials.yaml"


def read_dsh_refs(path: Path | None = None) -> dict[str, str]:
    """Return the flat `REF: value` entries directly under the refs mapping."""
    try:
        text = (path or dsh_credential_path()).read_text()
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


def dsh_workspace() -> str:
    return read_dsh_refs().get(WORKSPACE_REF, "")


def _scalar(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        return value[1:-1]
    return value
