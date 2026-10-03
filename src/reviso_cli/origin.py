"""Server origin resolution."""
from __future__ import annotations

import os
from urllib.parse import urlparse

# The hosted product. Self-hosted and local development override this with
# REVISO_SERVER rather than a build-time change.
DEFAULT_SERVER_URL = "https://reviso.work"


def configured_origin(env: dict | None = None,
                      config: dict | None = None) -> str:
    env = os.environ if env is None else env
    config = config or {}
    for key in ("REVISO_SERVER", "REVISO_PUBLIC_URL"):
        origin = _clean(env.get(key, ""))
        if origin:
            return origin
    return _clean(config.get("server", "")) or DEFAULT_SERVER_URL


def is_loopback_origin(origin: str) -> bool:
    return _is_loopback_host(urlparse(origin).hostname or "")


def _is_loopback_host(host: str) -> bool:
    value = (host or "").strip().lower()
    if value in ("localhost", "::1"):
        return True
    return value.startswith("127.")


def _clean(value: object) -> str:
    return str(value or "").strip().rstrip("/")
