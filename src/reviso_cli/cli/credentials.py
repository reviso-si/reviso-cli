"""Resolve and refresh only the credentials belonging to the selected origin."""
import os
import time
from datetime import datetime

from ..origin import DEFAULT_SERVER_URL
from .credential_file import credential_lock, read_credentials, write_credentials
from .dsh_credentials import (
    EXPIRES_REF,
    SERVER_REF,
    TOKEN_REF,
    dsh_credential_path,
    dsh_expires_at,
    dsh_token_expired,
    read_dsh_refs,
)
from .oauth_http import OAuthFailure, oauth_json, server_origin

LOGIN_HINT = "Run reviso auth login --server https://reviso.work (or your configured server)."


def server_sources(legacy: dict, explicit: str = "") -> dict:
    return {"argument": explicit or "", "environment": os.environ.get("REVISO_SERVER", ""),
            "project_config": legacy.get("server", ""),
            "user_config": read_credentials().get("server", ""),
            "dsh_host": dsh_server()}


def selected_server(legacy: dict, explicit: str = "") -> str:
    return next((value for value in server_sources(legacy, explicit).values() if value), "")


def legacy_token(legacy: dict, server: str) -> str:
    bound = str(legacy.get("server") or "").rstrip("/")
    return legacy.get("automation_key", "") if bound == server.rstrip("/") else ""


def dsh_server() -> str:
    """The origin the DSH host recorded, normalized; '' when absent or invalid."""
    value = read_dsh_refs().get(SERVER_REF, "")
    if not value:
        return ""
    try:
        return server_origin(value)
    except ValueError:
        return ""


def dsh_token(server: str) -> str:
    """Token from the DSH host file, usable only on its paired origin.

    The host stores one connection's refs together; when the file records no
    origin the token pairs with the hosted default, mirroring the host's own
    fallback. It is never handed to a different origin, and an expired token
    resolves to '' so a dead credential is never sent.
    """
    refs = read_dsh_refs()
    token = refs.get(TOKEN_REF, "")
    if not token or dsh_token_expired(refs):
        return ""
    paired = dsh_server() or DEFAULT_SERVER_URL
    return token if server.rstrip("/") == paired else ""


def _fail_expired_dsh(server: str) -> None:
    """Name the dead DSH credential instead of failing as an opaque 401."""
    refs = read_dsh_refs()
    if not refs.get(TOKEN_REF, ""):
        return
    paired = dsh_server() or DEFAULT_SERVER_URL
    if server.rstrip("/") != paired:
        return
    expires = dsh_expires_at(refs)
    if expires is None or time.time() < expires:
        return
    expired_at = datetime.fromtimestamp(expires).astimezone().isoformat(timespec="seconds")
    raise SystemExit(
        f"DSH host credential {dsh_credential_path()} holds an expired Reviso "
        f"token for {paired} ({EXPIRES_REF} {expired_at}, local time). "
        "Reconnect the Reviso connection in DSH, or export "
        "REVISO_AUTOMATION_KEY.")


def access_token(server: str, legacy: dict) -> str:
    explicit = os.environ.get("REVISO_AUTOMATION_KEY")
    if explicit:
        return explicit
    server = server.rstrip("/")
    if server not in read_credentials().get("servers", {}):
        token = legacy_token(legacy, server) or dsh_token(server)
        if not token:
            _fail_expired_dsh(server)
        return token
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
