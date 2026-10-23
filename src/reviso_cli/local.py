"""Local mapping management — no Store imports, HTTP-only."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

from .errors import ValidationError
from .ids import sha256_text
from .paths import mapping_path, read_json, write_json


def canonical_review_url(result: dict) -> str:
    """Return the server-supplied URL without deriving a new one.

    The server owns the canonical product origin and route. Host aliases,
    proxies, and an embed host that differs from the API origin make local URL
    construction incorrect, so absent or malformed values fail closed.
    """
    value = str(result.get("review_url") or "")
    candidate = urlsplit(value)
    if candidate.scheme not in ("http", "https") or not candidate.netloc:
        raise ValidationError(
            "server did not return a canonical absolute review_url")
    return value


def write_mapping(result: dict, file_path: Path) -> dict:
    review_id = result["document_id"]
    mapping = {
        "document_id": review_id,
        "url": canonical_review_url(result),
        "local_path": str(file_path.resolve()),
        "repo_root": str(Path.cwd().resolve()),
        "base_server_version_id": result.get("version_id", ""),
        "published_file_hash": sha256_text(file_path.read_text()),
        "created_at": result.get("created_at", ""),
    }
    write_json(mapping_path(review_id), mapping)
    return mapping


def read_mapping(review_id: str) -> dict:
    return read_json(mapping_path(review_id))


def git_env(environ: dict | None = None) -> dict:
    """Return the process environment without inherited Git control variables."""
    env = dict(os.environ if environ is None else environ)
    for key in tuple(env):
        if key.startswith("GIT_"):
            env.pop(key, None)
    return env


def git_dirty_summary() -> str:
    try:
        result = subprocess.run(["git", "status", "--short"],
                                capture_output=True, text=True, check=False,
                                env=git_env())
    except OSError:
        return "git unavailable"
    if result.returncode != 0:
        return "not a git repo"
    lines = [line for line in result.stdout.splitlines() if line]
    return "clean" if not lines else f"{len(lines)} dirty entries"
