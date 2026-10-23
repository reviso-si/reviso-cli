"""V1.0 version/edit CLI commands."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .. import command_journal


def _base_choice(args: argparse.Namespace) -> str:
    explicit = (args.base_version_id or "").strip()
    force_latest = getattr(args, "force_latest", False)
    if explicit and force_latest:
        raise SystemExit(
            "--base-version-id and --force-latest are mutually exclusive")
    if not explicit and not force_latest:
        raise SystemExit(
            "--base-version-id is required for this write; read the current "
            "version with `reviso versions <document_id>` and pass it. Use "
            "--force-latest only when last-writer-wins is intentional.")
    return explicit


def _base_version(args: argparse.Namespace, client) -> str:
    explicit = _base_choice(args)
    if explicit:
        return explicit
    return client.latest_content(args.document_id)["version_id"]


def cmd_update(args: argparse.Namespace) -> None:
    path = Path(args.file)
    client = args.client_factory()
    content = path.read_text()
    fmt = format_file_arg(args, path)
    # Reject a missing/exclusive base before journal reservation; force-latest
    # resolves once inside reserve() and that concrete base is replayed on retry.
    _base_choice(args)
    # Journal key is USER inputs only -- NOT the dynamically resolved latest, so
    # a rerun after a lost response does not drift onto the version the first run
    # just committed. The concrete base resolved on first run is replayed via the
    # stored request, keeping operation_id + base_version_id in lockstep (P1c).
    parts = [args.document_id, content, args.description or "", fmt,
             args.agent_name or "", args.base_version_id or ""]

    def resolve() -> dict:
        return {"base_version_id": _base_version(args, client)}

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
    base = _base_version(args, client)
    result = client.rollback(args.document_id, args.target_version_id, base,
                             args.description)
    print(json.dumps(result, indent=2, sort_keys=True))


def add_version_commands(sub: argparse._SubParsersAction, client_factory) -> None:
    upd = sub.add_parser("update")
    upd.add_argument("document_id")
    upd.add_argument("file")
    upd.add_argument("--description", required=True)
    upd.add_argument("--base-version-id", help="Version the update was based on (required for CAS).")
    upd.add_argument("--force-latest", action="store_true", help="Explicitly read the latest version and allow last-writer-wins.")
    upd.add_argument("--format", choices=["markdown", "md", "html"])
    upd.add_argument("--agent-name", default="Agent")
    upd.set_defaults(func=cmd_update, client_factory=client_factory)
    vers = sub.add_parser("versions")
    vers.add_argument("document_id")
    vers.set_defaults(func=cmd_versions, client_factory=client_factory)
    diff = sub.add_parser("diff")
    diff.add_argument("document_id")
    diff.add_argument("from_version_id")
    diff.add_argument("to_version_id")
    diff.add_argument("--json", action="store_true")
    diff.set_defaults(func=cmd_diff, client_factory=client_factory)
    rb = sub.add_parser("rollback")
    rb.add_argument("document_id")
    rb.add_argument("target_version_id")
    rb.add_argument("--description", required=True)
    rb.add_argument("--base-version-id", help="Version the rollback was based on (required for CAS).")
    rb.add_argument("--force-latest", action="store_true", help="Explicitly read the latest version and allow last-writer-wins.")
    rb.set_defaults(func=cmd_rollback, client_factory=client_factory)


def format_file_arg(args: argparse.Namespace, path: Path) -> str:
    if getattr(args, "format", None):
        return "html" if args.format == "html" else "markdown"
    return "html" if path.suffix.lower() in (".html", ".htm") else "markdown"
