"""Browser authorization using a temporary loopback listener, state and PKCE."""
import hashlib
import secrets
import time
import webbrowser
from base64 import urlsafe_b64encode
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlsplit

from .credentials import save_login, token_fields
from .oauth_http import OAuthFailure, oauth_json


class LoopbackServer(HTTPServer):
    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(2)
        return connection, address


def _handler(state: str, result: dict):
    class Callback(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urlsplit(self.path)
            params = parse_qs(parsed.query)
            valid = (parsed.path == "/callback" and len(params.get("state", [])) == 1
                     and secrets.compare_digest(params["state"][0], state))
            code = params.get("code", [])
            error = params.get("error", [])
            valid = valid and ((len(code) == 1 and not error) or (len(error) == 1 and not code))
            if valid:
                result.update(code=code[0] if code else "", error=bool(error))
            self.send_response(200 if valid else 400)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(b"Authorization received. Return to the Reviso CLI to confirm login."
                             if valid else b"Invalid callback. Return to the Reviso CLI and retry.")

        def log_message(self, format, *args):
            pass
    return Callback


def _metadata(server: str) -> dict:
    data = oauth_json(server + "/.well-known/oauth-authorization-server")
    for field, path in (("authorization_endpoint", "/oauth/authorize"),
                        ("token_endpoint", "/oauth/token"),
                        ("registration_endpoint", "/oauth/register")):
        if data.get(field) != server + path:
            raise OAuthFailure("endpoint_origin_mismatch")
    if data.get("issuer") != server or "S256" not in data.get("code_challenge_methods_supported", []):
        raise OAuthFailure("unsupported_server")
    return data


def browser_login(server: str, previous: dict, *, timeout: float = 180, no_browser=False) -> dict:
    metadata = _metadata(server)
    state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
    result = {}
    port = urlsplit(previous.get("redirect_uri", "")).port or 0
    try:
        listener = LoopbackServer(("127.0.0.1", port), _handler(state, result))
    except OSError:
        listener = LoopbackServer(("127.0.0.1", 0), _handler(state, result))
    with listener:
        listener.timeout = 0.25
        redirect = f"http://127.0.0.1:{listener.server_port}/callback"
        client_id = _register(metadata, previous, redirect)
        challenge = urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        query = {"response_type": "code", "client_id": client_id, "redirect_uri": redirect,
                 "resource": server + "/mcp", "scope": "mcp", "state": state,
                 "code_challenge": challenge, "code_challenge_method": "S256", "client_kind": "cli"}
        url = metadata["authorization_endpoint"] + "?" + urlencode(query)
        print("Open this URL to sign in (waiting up to " + str(int(timeout)) + " seconds):\n" + url, flush=True)
        if not no_browser:
            try:
                webbrowser.open(url)
            except webbrowser.Error:
                print("Browser could not open; use the URL above on this machine.", flush=True)
        deadline = time.monotonic() + timeout
        while not result and time.monotonic() < deadline:
            listener.handle_request()
    if not result or result.get("error"):
        raise OAuthFailure("access_denied" if result else "callback_timeout")
    payload = oauth_json(metadata["token_endpoint"], {
        "grant_type": "authorization_code", "client_id": client_id,
        "redirect_uri": redirect, "resource": server + "/mcp",
        "code": result["code"], "code_verifier": verifier}, form=True)
    fields = token_fields(payload, require_refresh="refresh_token" in metadata.get("grant_types_supported", []))
    entry = {"client_id": client_id, "redirect_uri": redirect, **fields}
    save_login(server, entry)
    return entry


def _register(metadata: dict, previous: dict, redirect: str) -> str:
    if previous.get("client_id") and previous.get("redirect_uri") == redirect:
        return previous["client_id"]
    result = oauth_json(metadata["registration_endpoint"], {
        "client_name": "Reviso CLI", "redirect_uris": [redirect],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"], "token_endpoint_auth_method": "none"})
    if not isinstance(result.get("client_id"), str) or not result["client_id"]:
        raise OAuthFailure("invalid_registration_response")
    return result["client_id"]
