"""Local mapping management — no Store imports, HTTP-only."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .document_route_keys import public_document_path
from .origin import DEFAULT_SERVER_URL
from .ids import sha256_text
from .paths import config_path, mapping_path, read_json, write_json


def _server_url() -> str:
    env = os.environ.get("REVISO_SERVER")
    if env:
        return env
    cfg_path = config_path()
    if cfg_path.exists():
        cfg = read_json(cfg_path)
        return cfg.get("server", DEFAULT_SERVER_URL)
    return DEFAULT_SERVER_URL


def write_mapping(result: dict, file_path: Path) -> dict:
    review_id = result["document_id"]
    mapping = {
        "document_id": review_id,
        "url": f"{_server_url()}{public_document_path(review_id)}",
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


def git_dirty_summary() -> str:
    try:
        result = subprocess.run(["git", "status", "--short"],
                                capture_output=True, text=True, check=False)
    except OSError:
        return "git unavailable"
    if result.returncode != 0:
        return "not a git repo"
    lines = [line for line in result.stdout.splitlines() if line]
    return "clean" if not lines else f"{len(lines)} dirty entries"
