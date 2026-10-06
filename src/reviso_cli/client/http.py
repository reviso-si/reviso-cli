"""HTTP transport helpers for the Reviso CLI client."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from urllib.parse import urlsplit

from .errors import raise_for_status

TIMEOUT = 30
# An error body is an envelope, not a payload. 1 MiB is orders of magnitude
# larger than any envelope this server emits, so a well-behaved error still
# arrives whole and parses -- but a proxy that answers a failed request with
# an HTML page, or an endpoint that never stops writing, can no longer make
# the agent read it all into memory.
MAX_ERROR_BODY = 1024 * 1024


def request_json(base_url: str, key: str | None, method: str, path: str, *,
                 body: dict | None = None,
                 guest_id: str | None = None,
                 guest_token: str | None = None,
                 source: str = "python_client",
                 guard: Callable[[str, str | None, str | None], None] | None = None) -> dict:
    if guard is not None:
        guard(path, guest_id, guest_token)
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(
        f"{base_url}{path}", data=data,
        headers=_headers(data, key, guest_id, guest_token), method=method)
    if source in ("stdio", "hosted_mcp", "python_client"):
        req.add_header("X-Reviso-Client", source)
    try:
        with urllib.request.build_opener(CredentialRedirect).open(
                req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        # Do NOT truncate below MAX_ERROR_BODY: the body is usually the
        # server's own error envelope, and slicing it mid-JSON makes it
        # unparseable, so a 400 VALIDATION_FAILED came back to the agent
        # stamped INTERNAL_ERROR with a chopped JSON blob as its message.
        # raise_for_status truncates only the free-text fallback. The cap
        # here is a memory bound on a body we do not control, not a display
        # limit -- anything that hits it was never a parseable envelope.
        raise_for_status(
            e.code, e.read(MAX_ERROR_BODY).decode("utf-8", errors="replace"))
    except urllib.error.URLError as e:
        raise SystemExit(f"connection error: {e.reason}") from e


def _headers(data: bytes | None, key: str | None,
             guest_id: str | None, guest_token: str | None) -> dict:
    headers = {"Content-Type": "application/json"} if data is not None else {}
    if guest_id and guest_token:
        headers["X-Guest-Id"] = guest_id
        headers["X-Guest-Token"] = guest_token
    elif key:
        headers["Authorization"] = f"Bearer {key}"
    return headers


class CredentialRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse a redirect that leaves the origin the request was sent to.

    The default handler follows a redirect and carries the request headers with
    it, so a 302 pointing at another host would hand that host the automation
    key -- or a guest token -- in an Authorization header. A redirect that
    changes scheme or host is far more likely to be an attack or a
    misconfiguration than something this client needs, so it fails instead.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        before, after = urlsplit(req.full_url), urlsplit(newurl)
        if (before.scheme, before.netloc) != (after.scheme, after.netloc):
            raise urllib.error.URLError("cross-origin redirect refused")
        return super().redirect_request(req, fp, code, msg, headers, newurl)
