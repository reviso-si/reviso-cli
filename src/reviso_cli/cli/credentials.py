"""Resolve and refresh only the credentials belonging to the selected origin."""
import os
import time

from .credential_file import credential_lock, read_credentials, write_credentials
from .oauth_http import OAuthFailure, oauth_json, server_origin

LOGIN_HINT = "Run reviso auth login --server https://reviso.work (or your configured server)."


def server_sources(legacy: dict, explicit: str = "") -> dict:
    return {"argument": explicit or "", "environment": os.environ.get("REVISO_SERVER", ""),
            "project_config": legacy.get("server", ""),
            "user_config": read_credentials().get("server", "")}


def selected_server(legacy: dict, explicit: str = "") -> str:
    return next((value for value in server_sources(legacy, explicit).values() if value), "")


def legacy_token(legacy: dict, server: str) -> str:
    bound = str(legacy.get("server") or "").rstrip("/")
    return legacy.get("automation_key", "") if bound == server.rstrip("/") else ""


def access_token(server: str, legacy: dict) -> str:
    explicit = os.environ.get("REVISO_AUTOMATION_KEY")
    if explicit:
        return explicit
    server = server.rstrip("/")
    if server not in read_credentials().get("servers", {}):
        return legacy_token(legacy, server)
    with credential_lock():
        data = read_credentials()
        entry = data.get("servers", {}).get(server, {})
        if entry.get("reauth_required"):
            raise OAuthFailure("login_required")
        token = entry.get("access_token", "")
        if not entry.get("refresh_token"):
            if entry.get("expires_at") and time.time() >= entry["expires_at"]:
                raise OAuthFailure("login_required")
            return token
        if time.time() < entry.get("expires_at", 0) - 60:
            return token
        # Persist the in-flight state before sending a single-use credential.
        # After a crash/ambiguous timeout, login again instead of replaying it.
        entry["reauth_required"] = True
        write_credentials(data)
        try:
            payload = oauth_json(server_origin(server) + "/oauth/token", {
                "grant_type": "refresh_token", "refresh_token": entry["refresh_token"],
                "client_id": entry["client_id"], "resource": server + "/mcp"}, form=True)
        except OAuthFailure as exc:
            if exc.oauth_code == "rate_limited":
                entry.pop("reauth_required", None)
                write_credentials(data)
            raise
        entry.update(token_fields(payload, require_refresh=True))
        entry.pop("reauth_required", None)
        write_credentials(data)
        return entry["access_token"]


def token_fields(payload: dict, *, require_refresh: bool = True) -> dict:
    if (not isinstance(payload.get("access_token"), str)
            or not payload["access_token"]
            or payload.get("token_type", "").lower() != "bearer"
            or not isinstance(payload.get("expires_in"), (int, float))
            or not 0 < payload["expires_in"] <= 31536000):
        raise OAuthFailure("invalid_token_response")
    refresh = payload.get("refresh_token")
    if (require_refresh or refresh is not None) and (not isinstance(refresh, str) or not refresh):
        raise OAuthFailure("invalid_token_response")
    result = {"access_token": payload["access_token"],
              "expires_at": time.time() + payload["expires_in"]}
    if refresh:
        result.update(refresh_token=refresh, refresh_expires_at=payload.get("refresh_expires_at", ""))
    return result


def save_login(server: str, entry: dict) -> None:
    with credential_lock():
        data = read_credentials()
        data.setdefault("servers", {})[server] = entry
        data["server"] = server
        write_credentials(data)


def forget_login(server: str) -> None:
    with credential_lock():
        data = read_credentials()
        data.get("servers", {}).pop(server, None)
        if data.get("server") == server:
            data.pop("server", None)
        write_credentials(data)
