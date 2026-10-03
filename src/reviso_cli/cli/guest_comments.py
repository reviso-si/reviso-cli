"""CLI commands for guest comment workflows."""
from __future__ import annotations

import argparse
import json
from typing import Callable


def add_guest_comment_commands(sub: argparse._SubParsersAction,
                               client_factory: Callable) -> None:
    guest = sub.add_parser("guest")
    guest.add_argument("document_id"); guest.add_argument("--name", required=True)
    guest.add_argument("--email")
    guest.set_defaults(func=lambda a: cmd_guest(a, client_factory))
    comment = sub.add_parser("comment")
    comment.add_argument("document_id")
    comment.add_argument("--guest-id", default="")
    comment.add_argument("--guest-token", default="")
    comment.add_argument("--body", required=True)
    comment.add_argument("--anchor-type", choices=["block", "selection"],
                         default="block")
    comment.add_argument("--block-id", default="")
    comment.add_argument("--quote", default="")
    comment.set_defaults(func=lambda a: cmd_comment(a, client_factory))
    reply = sub.add_parser("reply")
    reply.add_argument("thread_id")
    reply.add_argument("--guest-id", default="")
    reply.add_argument("--guest-token", default="")
    reply.add_argument("--body", required=True)
    reply.set_defaults(func=lambda a: cmd_reply(a, client_factory))
    resolve = sub.add_parser("resolve")
    resolve.add_argument("thread_id")
    resolve.add_argument("--guest-id", default="")
    resolve.add_argument("--guest-token", default="")
    resolve.add_argument("--reason", required=True)
    resolve.set_defaults(func=lambda a: cmd_resolve(a, client_factory))


def cmd_guest(args: argparse.Namespace, client_factory: Callable) -> None:
    result = client_factory().guest(args.document_id, args.name, args.email or None)
    print(json.dumps(result, indent=2, sort_keys=True))


def cmd_comment(args: argparse.Namespace, client_factory: Callable) -> None:
    anchor = {"type": args.anchor_type, "block_id": args.block_id,
              "quote": args.quote}
    result = client_factory().comment(args.document_id, args.guest_id,
                                      args.guest_token, args.body, anchor)
    print(json.dumps(result, indent=2, sort_keys=True))


def cmd_reply(args: argparse.Namespace, client_factory: Callable) -> None:
    result = client_factory().reply(args.thread_id, args.guest_id,
                                    args.guest_token, args.body)
    print(json.dumps(result, indent=2, sort_keys=True))


def cmd_resolve(args: argparse.Namespace, client_factory: Callable) -> None:
    result = client_factory().resolve(args.thread_id, args.guest_id,
                                      args.guest_token, args.reason)
    print(json.dumps(result, indent=2, sort_keys=True))
