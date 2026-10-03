"""Access levels used by invites and share links.

The three levels below are the vocabulary a user types and sees. What each level
resolves to on the server is deliberately not represented here: the server owns
that mapping, and the client sends the level, not an expanded result.
"""
from __future__ import annotations

ACCESS_TO_ROLE = {
    "view": "viewer",
    "comment": "commenter",
    "edit": "editor",
}

VALID_ACCESS = tuple(ACCESS_TO_ROLE)


def normalize_access(access: str) -> str:
    value = str(access or "comment").strip()
    if value not in ACCESS_TO_ROLE:
        raise ValueError("access must be view, comment, or edit")
    return value


def role_for_access(access: str) -> str:
    return ACCESS_TO_ROLE[normalize_access(access)]


def access_from_body(body: dict) -> str:
    if str(body.get("role", "")).strip():
        raise ValueError("role is no longer accepted; pass access")
    return normalize_access(str(body.get("access") or "comment"))


def invite_access_from_body(body: dict) -> str:
    return access_from_body(body)


def invite_for_public(item: dict) -> dict:
    result = {key: value for key, value in item.items() if key != "role"}
    result["access"] = normalize_access(str(item.get("access") or "comment"))
    return result


def invite_list_for_public(result: dict) -> dict:
    return {
        **result,
        "invites": [invite_for_public(item) for item in result.get("invites", [])],
    }
