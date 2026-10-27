"""Request size preflight shared by the publish and update commands."""
from __future__ import annotations

import json
import os

from ..errors import ValidationError

# The server rejects oversized JSON bodies; failing here saves the upload and
# reports sizes the server would. The ceiling is env-overridable so a
# deployment with a different limit can tune the CLI to match.
MAX_PUBLISH_JSON_BYTES = 37748736
MB = 1024 * 1024


def max_publish_json_bytes(env: dict | None = None) -> int:
    raw = (os.environ if env is None else env).get("REVISO_MAX_PUBLISH_JSON_BYTES", "")
    try:
        limit = int(str(raw).strip())
    except ValueError:
        return MAX_PUBLISH_JSON_BYTES
    return limit if limit > 0 else MAX_PUBLISH_JSON_BYTES


def check_publish_size(body: dict, env: dict | None = None) -> None:
    """Reject a request body larger than the server's JSON ceiling."""
    limit = max_publish_json_bytes(env)
    size = len(json.dumps(body).encode("utf-8"))
    if size <= limit:
        return
    raise ValidationError(
        f"publish payload is {size / MB:.1f} MB, over the {limit / MB:.1f} MB "
        "limit set by REVISO_MAX_PUBLISH_JSON_BYTES. Reduce embedded images or "
        "reference uploaded assets instead of inlining them.")
