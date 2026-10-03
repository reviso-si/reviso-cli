"""V1.0 version/edit CLI commands."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .. import command_journal


def cmd_update(args: argparse.Namespace) -> None:
    path = Path(args.file)
    client = args.client_factory()
    content = path.read_text()
    fmt = format_file_arg(args, path)
    # Journal key is USER inputs only -- NOT the dynamically resolved latest, so
    # a rerun after a lost response does not drift onto the version the first run
    # just committed. The concrete base resolved on first run is replayed via the
    # stored request, keeping operation_id + base_version_id in lockstep (P1c).
    parts = [args.document_id, content, args.description or "", fmt,
             args.agent_name or "", args.base_version_id or ""]

    def resolve() -> dict:
        base = (args.base_version_id
                or client.latest_content(args.document_id)["version_id"])
        return {"base_version_id": base}

    entry = command_journal.reserve("update", parts, resolve=resolve)
    op = entry["operation_id"]
    base = entry["request"]["base_version_id"]
    result = client.update(args.document_id, content, base,
                           args.description, fmt,
                           args.agent_name, operation_id=op)
    print(json.dumps(result, indent=2, sort_keys=True))
    # Forget only after the local output step succeeded (see cmd_publish).
    command_journal.forget("update", parts)


def cmd_versions(args: argparse.Namespace) -> None:
    print(json.dumps(args.client_factory().versions(args.document_id),
                     indent=2, sort_keys=True))


def cmd_diff(args: argparse.Namespace) -> None:
    result = args.client_factory().diff(args.document_id, args.from_version_id,
                                        args.to_version_id)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print("\n".join(result.get("unified_diff", [])))


def cmd_rollback(args: argparse.Namespace) -> None:
    client = args.client_factory()
    base = args.base_version_id or client.latest_content(args.document_id)["version_id"]
    result = client.rollback(args.document_id, args.target_version_id, base,
                             args.description)
    print(json.dumps(result, indent=2, sort_keys=True))


def add_version_commands(sub: argparse._SubParsersAction, client_factory) -> None:
    upd = sub.add_parser("update")
    upd.add_argument("document_id"); upd.add_argument("file")
    upd.add_argument("--description", required=True)
    upd.add_argument("--base-version-id", help="Version to base the update on (CAS). Omit to auto-base on the latest version (last-writer-wins); pass it for documents others are editing.")
    upd.add_argument("--format", choices=["markdown", "md", "html"])
    upd.add_argument("--agent-name", default="Agent")
    upd.set_defaults(func=cmd_update, client_factory=client_factory)
    vers = sub.add_parser("versions")
    vers.add_argument("document_id")
    vers.set_defaults(func=cmd_versions, client_factory=client_factory)
    diff = sub.add_parser("diff")
    diff.add_argument("document_id"); diff.add_argument("from_version_id")
    diff.add_argument("to_version_id"); diff.add_argument("--json", action="store_true")
    diff.set_defaults(func=cmd_diff, client_factory=client_factory)
    rb = sub.add_parser("rollback")
    rb.add_argument("document_id"); rb.add_argument("target_version_id")
    rb.add_argument("--description", required=True)
    rb.add_argument("--base-version-id")
    rb.set_defaults(func=cmd_rollback, client_factory=client_factory)


def format_file_arg(args: argparse.Namespace, path: Path) -> str:
    if getattr(args, "format", None):
        return "html" if args.format == "html" else "markdown"
    return "html" if path.suffix.lower() in (".html", ".htm") else "markdown"
