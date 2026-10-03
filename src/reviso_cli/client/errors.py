"""Client-side HTTP error handling."""
from __future__ import annotations

import json


def raise_for_status(code: int, detail: str) -> None:
    """Turn an HTTP error body into SystemExit, keeping the server's own code.

    `detail` must be the FULL response body. Truncating it upstream broke
    envelope parsing and downgraded classified server errors to INTERNAL_ERROR;
    the cap belongs here, on the unstructured fallback only.
    """
    try:
        parsed = json.loads(detail) if isinstance(detail, str) else detail
        err = parsed.get("error", {}) if isinstance(parsed, dict) else {}
        if err.get("code"):
            hint = err.get("hint", "")
            msg = err.get("message", detail)
            suffix = f" (hint: {hint})" if hint else ""
            exc = SystemExit(f"{err['code']}: {msg}{suffix}")
            exc.error_envelope = parsed
            raise exc
    except (json.JSONDecodeError, AttributeError):
        pass
    prefix = {401: "auth", 403: "forbidden", 404: "not found",
              409: "conflict", 429: "rate limited"}
    raise SystemExit(f"{prefix.get(code, f'HTTP {code}')}: {detail[:300]}")
