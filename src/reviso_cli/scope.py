"""Workspace scope resolution for create and import.

A create needs a workspace. Prefer an explicit value, then the environment, then
the saved config. When an account-scoped key is in play the server resolves a
default from the account's memberships, so an empty workspace is passed through
instead of failing here.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from .origin import configured_origin, is_loopback_origin


@dataclass(frozen=True)
class CreateScope:
    workspace_id: str
    parent_id: str
    source: str


def resolve_agent_create_scope(
    *,
    explicit_workspace_id: str = "",
    explicit_parent_id: str = "",
    env: dict | None = None,
    config: dict | None = None,
    automation_workspace_id: str = "",
    has_automation_key: bool = False,
) -> CreateScope:
    env = env or os.environ
    config = config or {}
    candidates = [
        ("argument", explicit_workspace_id),
        ("env", env.get("REVISO_WORKSPACE_ID", "")),
        ("config", config.get("workspace_id", "")),
    ]
    for source, value in candidates:
        workspace_id = str(value or "").strip()
        if workspace_id:
            return CreateScope(workspace_id, str(explicit_parent_id or ""), source)
    if has_automation_key:
        return CreateScope("", str(explicit_parent_id or ""), "agent-default")
    if _workspace_required(env, config):
        raise SystemExit(
            "workspace_id required for create/import. Pass --workspace-id, set "
            "REVISO_WORKSPACE_ID, or copy your workspace id from Settings -> "
            "Integrations in the browser.")
    return CreateScope("", str(explicit_parent_id or ""), "local-default")


def _hosted(env: dict, config: dict) -> bool:
    if str(env.get("REVISO_HOSTED") or config.get("hosted") or "") == "1":
        return True
    if str(env.get("REVISO_REQUIRE_HTTPS") or "") == "1":
        return True
    origin = configured_origin(env, config)
    return bool(origin and not is_loopback_origin(origin))


def _workspace_required(env: dict, config: dict) -> bool:
    if _hosted(env, config):
        return True
    return str(env.get("REVISO_ALLOW_DEFAULT_WORKSPACE_CREATE") or "") != "1"
