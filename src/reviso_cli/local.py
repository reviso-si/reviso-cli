"""Local mapping management — no Store imports, HTTP-only."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

from .document_route_keys import public_document_path
from .origin import DEFAULT_SERVER_URL
from .ids import sha256_text
from .paths import config_path, mapping_path, read_json, write_json


def _server_url() -> str:
    from .cli.credentials import selected_server
    from .cli.oauth_http import server_origin

    path = config_path()
    cfg = read_json(path) if path.exists() else {}
    return server_origin(selected_server(cfg) or DEFAULT_SERVER_URL)


def _canonical_review_url(result: dict, review_id: str) -> str:
    server = _server_url()
    explicit = str(result.get("review_url") or "")
    if explicit:
        candidate = urlsplit(explicit)
        expected = urlsplit(server)
        if candidate.scheme not in ("http", "https") or not candidate.netloc:
            raise ValueError("review_url must be an absolute HTTP(S) URL")
        if (candidate.scheme, candidate.netloc) != (expected.scheme, expected.netloc):
            raise ValueError("review_url origin does not match the selected Reviso server")
        return explicit
    return f"{server}{public_document_path(review_id)}"


def write_mapping(result: dict, file_path: Path) -> dict:
    review_id = result["document_id"]
    mapping = {
        "document_id": review_id,
        "url": _canonical_review_url(result, review_id),
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
