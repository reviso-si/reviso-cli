"""CLI invite commands.

Anonymous share links are deliberately not part of this client. A share link
carries a bearer token in its URL, and creating one is a browser action where the
person handing it out can see who it is going to. Invites by email are here.
"""
from __future__ import annotations

import argparse
import json
from typing import Callable

from ..client import RevisoClient
from ..access import invite_access_from_body, invite_for_public, invite_list_for_public


def add_invite_commands(sub: argparse._SubParsersAction,
                        client_factory: Callable[[], RevisoClient]) -> None:
    invite = sub.add_parser("invite")
    invite_sub = invite.add_subparsers(dest="invite_cmd", required=True)
    create = invite_sub.add_parser("create")
    create.add_argument("document_id")
    create.add_argument("--email", required=True)
    create.add_argument("--access", default="",
                        choices=["view", "comment", "edit"])
    create.add_argument("--json", action="store_true")
    create.set_defaults(func=lambda a: _create(a, client_factory))
    list_cmd = invite_sub.add_parser("list")
    list_cmd.add_argument("document_id")
    list_cmd.add_argument("--json", action="store_true")
    list_cmd.set_defaults(func=lambda a: _list(a, client_factory))
    revoke = invite_sub.add_parser("revoke")
    revoke.add_argument("invite_id")
    revoke.add_argument("--json", action="store_true")
    revoke.set_defaults(func=lambda a: _revoke(a, client_factory))


def _create(args: argparse.Namespace,
            client_factory: Callable[[], RevisoClient]) -> None:
    body = {}
    if args.access:
        body["access"] = args.access
    access = invite_access_from_body(body)
    result = invite_for_public(
        client_factory().create_invite(
            args.document_id, args.email, access))
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
        return
    if result.get("account_shared"):
        label = "account share updated" if result.get("existing") else "shared with account"
        print(f"{label}: {result['grant_id']}")
    elif result.get("existing"):
        print(f"pending invite already exists: {result['invite_id']}")
    else:
        print(result.get("invite_url") or result["invite_id"])


def _list(args: argparse.Namespace,
          client_factory: Callable[[], RevisoClient]) -> None:
    result = invite_list_for_public(client_factory().list_invites(args.document_id))
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
        return
    for item in result.get("invites", []):
        print(f"{item['id']}\t{item['status']}\t{item['access']}\t{item['email']}")


def _revoke(args: argparse.Namespace,
            client_factory: Callable[[], RevisoClient]) -> None:
    result = client_factory().revoke_invite(args.invite_id)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"{result['id']}: {result['status']}")
