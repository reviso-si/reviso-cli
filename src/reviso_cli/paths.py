"""Local state paths.

State is per user, not per working directory: a login saved in one terminal has
to be visible from the next one. Override the root with REVISO_STATE_DIR.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

_SAFE_ID = re.compile(r'^[a-zA-Z0-9_.-]{1,64}$')


def _override(name: str) -> Path | None:
    value = os.environ.get(name, "").strip()
    if not value:
        return None
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError(f"{name} must be an absolute path")
    return path.resolve()


def local_dir() -> Path:
    explicit = _override("REVISO_STATE_DIR")
    if explicit:
        return explicit
    base = _override("XDG_STATE_HOME") or Path.home() / ".local" / "state"
    return base / "reviso"


def ensure_local() -> Path:
    base = local_dir()
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    for name in ("reviews", "packets"):
        (base / name).mkdir(parents=True, exist_ok=True)
    return base


def read_json(path: Path) -> Any:
    return json.loads(path.read_text())


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def _safe(name: str) -> str:
    if not _SAFE_ID.match(name) or '..' in name:
        raise ValueError(f"invalid id for path: {name!r}")
    return name


def mapping_path(review_id: str) -> Path:
    return ensure_local() / "reviews" / f"{_safe(review_id)}.json"


def packet_path(packet_id: str, fmt: str) -> Path:
    return ensure_local() / "packets" / f"{_safe(packet_id)}.{_safe(fmt)}"


def config_path() -> Path:
    return ensure_local() / "config.json"
