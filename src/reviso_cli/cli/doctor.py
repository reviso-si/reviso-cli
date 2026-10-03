"""CLI environment diagnostics."""
from __future__ import annotations

import urllib.error
import urllib.request


def doctor_report(client, server_url: str, token: str,
                  workspace_id: str = "") -> dict:
    checks = [
        _static("server_config", bool(server_url), server_url or "not set"),
        _static("auth_token", bool(token), _token_message(token)),
        _call("health", client.health),
        _call("ready", client.ready),
        _call("version", client.version_info),
        _call("workspaces", client.workspaces),
        _mcp_check(server_url),
    ]
    if workspace_id:
        checks.append(_workspace_check(checks[-2], workspace_id))
    return {"ok": all(check["status"] != "fail" for check in checks),
            "checks": checks}


def print_doctor(report: dict) -> None:
    for check in report["checks"]:
        print(f"{check['status'].upper()}\t{check['name']}\t{check['message']}")
    print("OK" if report["ok"] else "FAILED")


def _static(name: str, ok: bool, message: str) -> dict:
    return {"name": name, "status": "ok" if ok else "warn",
            "message": message}


def _call(name: str, func) -> dict:
    try:
        payload = func()
    except SystemExit as exc:
        return {"name": name, "status": "fail", "message": str(exc)}
    except Exception as exc:  # noqa: BLE001 - diagnostic boundary.
        return {"name": name, "status": "fail", "message": str(exc)}
    return {"name": name, "status": "ok", "message": _summary(payload),
            "payload": payload}


def _mcp_check(server_url: str) -> dict:
    if not server_url:
        return {"name": "mcp_endpoint", "status": "warn",
                "message": "server not set"}
    req = urllib.request.Request(
        f"{server_url.rstrip('/')}/mcp",
        headers={"Accept": "application/json"},
        method="GET",
    )
    try:
        urllib.request.urlopen(req, timeout=5).read()
    except urllib.error.HTTPError as exc:
        if exc.code == 405:
            return {"name": "mcp_endpoint", "status": "ok",
                    "message": "reachable; POST JSON-RPC expected"}
        return {"name": "mcp_endpoint", "status": "fail",
                "message": f"HTTP {exc.code}"}
    except Exception as exc:  # noqa: BLE001 - diagnostic boundary.
        return {"name": "mcp_endpoint", "status": "fail",
                "message": str(exc)}
    return {"name": "mcp_endpoint", "status": "ok", "message": "reachable"}


def _workspace_check(workspaces: dict, workspace_id: str) -> dict:
    rows = (workspaces.get("payload") or {}).get("workspaces") or []
    found = any(row.get("workspace_id") == workspace_id for row in rows)
    return {"name": "workspace_scope", "status": "ok" if found else "fail",
            "message": workspace_id if found else f"{workspace_id} not visible"}


def _token_message(token: str) -> str:
    return "set" if token else "missing REVISO_AUTOMATION_KEY"


def _summary(payload: dict) -> str:
    if "workspaces" in payload:
        return f"{len(payload['workspaces'])} workspaces"
    if "version" in payload:
        return str(payload["version"])
    if "status" in payload:
        return str(payload["status"])
    return "ok"
