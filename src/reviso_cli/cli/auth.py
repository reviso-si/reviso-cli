"""CLI login and status use the same origin/credential resolution as commands."""
import os
import time

from ..client import RevisoClient
from .credential_file import credential_path, read_credentials
from .credentials import (
    LOGIN_HINT,
    access_token,
    forget_login,
    legacy_token,
    save_login,
    selected_server,
    server_sources,
)
from .oauth_http import server_origin
from .oauth_login import browser_login


class AuthenticatedClient(RevisoClient):
    def __init__(self, server, key, config):
        super().__init__(server, key)
        self._config = config

    def _request(self, method, path, **kwargs):
        public = path in {"/healthz", "/readyz", "/version"}
        guest = kwargs.get("guest_id") and kwargs.get("guest_token")
        self._key = None if public or guest else access_token(self.url, self._config) or None
        return super()._request(method, path, **kwargs)


def auth_command(args, legacy):
    server = selected_server(legacy, args.server)
    server = server_origin(server) if server else ""
    if args.action == "status":
        return _status(server, legacy, args.server)
    if args.action == "logout":
        forget_login(server)
        print("Removed saved login for this server. Revoke the connection in Settings > Integrations.")
        if os.environ.get("REVISO_AUTOMATION_KEY") or legacy_token(legacy, server):
            print("An environment or legacy project key still exists; remove it separately.")
        return
    server = server or "https://reviso.work"
    key = args.key or os.environ.get("REVISO_AUTOMATION_KEY", "")
    if key:
        RevisoClient(server, key)._request("GET", "/api/agent-connection/self")
        save_login(server, {"access_token": key})
    else:
        previous = read_credentials().get("servers", {}).get(server, {})
        browser_login(server, previous, no_browser=getattr(args, "no_browser", False))
    print(f"Logged in to {server}. Credentials saved privately at {credential_path()}.")


def _status(server, legacy, explicit=""):
    sources = server_sources(legacy, explicit)
    selected = next((key for key, value in sources.items() if value), "none")
    print(f"server: {server or '(not configured)'}")
    print(f"server_source: {selected}")
    for key, value in sources.items():
        print(f"server_{key}: {_display_server(value)}")
    if not server:
        print(LOGIN_HINT)
        return
    entry = read_credentials().get("servers", {}).get(server.rstrip("/"), {})
    if os.environ.get("REVISO_AUTOMATION_KEY"):
        state = "environment key (not checked with server)"
    elif entry.get("reauth_required"):
        state = "login required; " + LOGIN_HINT
    elif entry.get("refresh_token"):
        state = "OAuth saved; refresh due" if entry.get("expires_at", 0) <= time.time() + 60 else "OAuth saved"
    elif entry.get("client_id") and entry.get("expires_at"):
        state = "login required; " + LOGIN_HINT if entry["expires_at"] <= time.time() else "OAuth saved; server has no refresh support"
    elif entry.get("access_token") or legacy_token(legacy, server):
        state = "saved key (not checked with server)"
    else:
        state = "not logged in; " + LOGIN_HINT
    print(f"auth: {state}")
    print(f"credentials: {credential_path()}")


def _display_server(value):
    if not value:
        return "(not set)"
    try:
        return server_origin(value)
    except ValueError:
        return "(invalid server origin)"
