"""Bounded OAuth HTTP requests without redirects or credential-bearing errors."""
import json
import urllib.error
import urllib.request
from urllib.parse import urlencode, urlsplit

class OAuthFailure(SystemExit):
    def __init__(self, code: str):
        self.oauth_code = code
        super().__init__(f"OAuth {code}. Run reviso auth login --server <your-server> to retry.")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise OAuthFailure("unexpected_redirect")


def server_origin(value: str) -> str:
    parsed = urlsplit(value)
    if (parsed.scheme not in ("https", "http") or not parsed.hostname
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in ("", "/")
            or any(c.isspace() or c == "\\" for c in value)):
        raise ValueError("--server must be an HTTPS origin (HTTP is allowed only on loopback).")
    if parsed.scheme == "http" and parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise ValueError("Use HTTPS for hosted Reviso; HTTP credentials are restricted to loopback.")
    if parsed.port is not None and not 1 <= parsed.port <= 65535:
        raise ValueError("Invalid server port")
    return f"{parsed.scheme}://{parsed.netloc.lower()}".rstrip("/")


def oauth_json(url: str, body: dict | None = None, *, form=False) -> dict:
    data = (urlencode(body).encode() if form else json.dumps(body).encode()) if body is not None else None
    req = urllib.request.Request(url, data=data, headers={
        "Accept": "application/json", "Content-Type":
        "application/x-www-form-urlencoded" if form else "application/json"})
    try:
        with urllib.request.build_opener(NoRedirect).open(req, timeout=15) as response:
            payload = json.loads(response.read(1024 * 1024))
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            raise OAuthFailure("rate_limited") from None
        try:
            error = json.loads(exc.read(4096)).get("error")
        except (ValueError, AttributeError):
            error = "http_error"
        allowed = {"invalid_grant", "invalid_client", "invalid_request", "invalid_scope", "access_denied"}
        raise OAuthFailure(error if error in allowed else "http_error") from None
    except (urllib.error.URLError, TimeoutError, ValueError):
        raise OAuthFailure("unavailable_or_invalid_response") from None
    if not isinstance(payload, dict) or payload.get("error"):
        raise OAuthFailure("invalid_response")
    return payload
