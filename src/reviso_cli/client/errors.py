"""Client-side HTTP error handling."""
from __future__ import annotations

import json

ERROR_CLASSES = {
    "not_connected", "auth_expired", "forbidden", "not_found",
    "conflict", "unavailable", "unsupported",
}


def stable_error_class(code: str | None, status: int) -> str:
    value = str(code or "")
    if value in ERROR_CLASSES:
        return value
    if "AUTH_REQUIRED" in value or "NOT_CONNECTED" in value:
        return "not_connected"
    if "TOKEN_EXPIRED" in value or status == 401:
        return "auth_expired"
    if "FORBIDDEN" in value or "PERMISSION" in value or status == 403:
        return "forbidden"
    if "NOT_FOUND" in value or status == 404:
        return "not_found"
    if "CONFLICT" in value or "CAS_" in value or status == 409:
        return "conflict"
    if "UNSUPPORTED" in value or "NOT_IMPLEMENTED" in value or status == 405:
        return "unsupported"
    return "unavailable" if status >= 500 or status == 0 else "forbidden"


def raise_for_status(code: int, detail: str) -> None:
    """Turn an HTTP error body into SystemExit with a stable top-level class.

    The server's original code and sanitized envelope remain diagnostics.
    """
    try:
        parsed = json.loads(detail) if isinstance(detail, str) else detail
        err = parsed.get("error", {}) if isinstance(parsed, dict) else {}
        if err.get("code"):
            original = str(err["code"])
            stable = stable_error_class(original, code)
            hint = err.get("hint", "")
            msg = err.get("message", detail)
            suffix = f" (hint: {hint})" if hint else ""
            exc = SystemExit(f"{stable}: {original}: {msg}{suffix}")
            exc.error_envelope = parsed
            exc.error_class = stable
            exc.original_code = original
            raise exc
    except (json.JSONDecodeError, AttributeError):
        pass
    stable = stable_error_class(None, code)
    exc = SystemExit(f"{stable}: {detail[:300]}")
    exc.error_class = stable
    raise exc
