"""Command line dispatcher. Every server call goes through RevisoClient."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

from .. import command_journal
from ..client import RevisoClient, publish_request_body
from ..deck_assets import asset_request, find_images, payload_summary, rewrite
from ..document_search import search_documents
from ..errors import ValidationError
from ..local import canonical_review_url, read_mapping, write_mapping
from ..origin import DEFAULT_SERVER_URL
from ..paths import config_path, packet_path, read_json, write_json
from ..scope import resolve_agent_create_scope
from .doctor import doctor_report, print_doctor
from .auth import AuthenticatedClient, auth_command
from .credentials import access_token, selected_server
from .dsh_credentials import dsh_workspace
from .oauth_http import server_origin
from .preflight import check_publish_size
from .guest_comments import add_guest_comment_commands
from .invites import add_invite_commands
from .versions import add_version_commands, format_file_arg

# Response blocks that are browser UI state. The human status line drops them;
# --json keeps them.
ACCESS_KEYS = ("effective_access", "security_policy")


def _load_config() -> dict:
    path = config_path()
    if path.exists():
        return read_json(path)
    return {}


def _server_url() -> str:
    return server_origin(selected_server(_load_config()) or DEFAULT_SERVER_URL)


def _automation_key(cfg: dict) -> str:
    return access_token(_server_url(), cfg)


def _client() -> RevisoClient:
    return AuthenticatedClient(_server_url(), None, _load_config())


def cmd_auth(args: argparse.Namespace) -> None:
    auth_command(args, _load_config())


def _draft_content(fmt: str, title: str, kind: str | None) -> str:
    """Small host document that can own uploaded assets before final publish."""
    safe_title = (title.replace("&", "&amp;").replace("<", "&lt;")
                  .replace(">", "&gt;"))
    if fmt == "html" and kind == "html_deck":
        return ('<div class="hr-deck" data-aspect-ratio="16:9" '
                'data-contract-version="html-deck/1">'
                '<section class="hr-slide" data-slide-id="s01">'
                f'<h1>{safe_title}</h1><p>Uploading images...</p>'
                '</section></div>')
    if fmt == "html":
        return f"<article><h1>{safe_title}</h1><p>Uploading images...</p></article>"
    return "# Uploading images...\n"


def _upload_embedded_images(client: RevisoClient, *, document_id: str,
                            content: str, path: Path, op: str) -> str:
    uploads = []
    for index, image in enumerate(find_images(content)):
        digest = hashlib.sha256(image.decoded).hexdigest()[:24]
        extension = image.mime.split("/", 1)[1].replace("jpeg", "jpg")
        uploaded = client.upload_image(
            document_id,
            **asset_request(
                image,
                file_name=f"{path.stem}-{index + 1}.{extension}",
                operation_id=f"{op}-asset-{index}-{digest}"[:199],
            ),
        )
        url = str(uploaded.get("url") or "")
        if not url:
            raise RuntimeError("image upload returned no asset URL")
        uploads.append((image, url))
    return rewrite(content, uploads)


def cmd_publish(args: argparse.Namespace) -> None:
    path = Path(args.file)
    scope = _workspace_scope(args.workspace_id or "", args.parent_id or "")
    content = path.read_text()
    fmt = format_file_arg(args, path)
    title = args.title or path.name
    kind, contract = args.kind, args.deck_contract_version
    options = {key: value for key, value in (("document_kind", kind), ("deck_contract_version", contract)) if value is not None}
    source_kind, source_session_id = _source_binding(args)
    if source_kind is not None:
        options["source_kind"] = source_kind
        options["source_session_id"] = source_session_id
    # A journaled operation_id is reused across reruns of THIS command, so a
    # crashed-then-rerun publish replays instead of double-creating. Cleared
    # only after every local success step has completed.
    parts = [title, content, fmt, args.description or "",
             scope.workspace_id, scope.parent_id]
    if options:
        parts.extend([kind or "", contract or "",
                      source_kind or "", source_session_id or ""])
    op = command_journal.operation_id_for("publish", parts)
    images = find_images(content)
    if getattr(args, "dry_run", False):
        print(json.dumps(payload_summary(content), indent=2, sort_keys=True))
        return

    client = _client()
    if (images and kind == "html_deck"
            and not getattr(args, "no_upload_images", False)):
        draft_options = dict(options)
        if kind == "html_deck":
            draft_options["deck_contract_version"] = contract or "html-deck/1"
        created = client.publish(
            title, _draft_content(fmt, title, kind), fmt, args.description,
            scope.workspace_id, scope.parent_id, operation_id=op,
            **draft_options)
        document_id = str(created.get("document_id") or "")
        base_version_id = str(created.get("version_id") or "")
        if not document_id or not base_version_id:
            raise RuntimeError("draft create returned no document/version id")
        final_content = _upload_embedded_images(
            client, document_id=document_id, content=content, path=path, op=op)
        result = client.update(
            document_id, final_content, base_version_id, args.description,
            source_format=fmt, operation_id=f"{op}-final"[:199],
            deck_contract_version=draft_options.get("deck_contract_version"))
        result = {
            **result,
            "document_id": document_id,
            "workspace_id": result.get(
                "workspace_id", created.get("workspace_id", scope.workspace_id)),
            "review_url": result.get("review_url") or created.get("review_url", ""),
        }
    else:
        check_publish_size(publish_request_body(
            title, content, fmt, args.description, scope.workspace_id,
            scope.parent_id, operation_id=op, **options))
        result = client.publish(
            title, content, fmt, args.description, scope.workspace_id,
            scope.parent_id, operation_id=op, **options)
    mapping = write_mapping(result, path)
    if getattr(args, "json", False):
        print(json.dumps({
            "document_id": mapping["document_id"],
            "version_id": mapping["base_server_version_id"],
            "workspace_id": result.get("workspace_id", scope.workspace_id),
            "review_url": mapping["url"],
        }, indent=2, sort_keys=True))
    else:
        print(mapping["url"])
    command_journal.forget("publish", parts)


def _source_binding(args: argparse.Namespace) -> tuple[str | None, str | None]:
    source_kind = getattr(args, "source_kind", None)
    source_session_id = getattr(args, "source_session_id", None)
    no_source = getattr(args, "no_source_binding", False)
    if no_source:
        if source_kind is not None or source_session_id is not None:
            raise ValidationError(
                "--no-source-binding cannot be combined with --source-kind or "
                "--source-session-id")
        return None, None
    if (source_kind is None) != (source_session_id is None):
        raise ValidationError(
            "--source-kind and --source-session-id must be supplied together")
    if source_kind is not None:
        source_kind = source_kind.strip()
        source_session_id = source_session_id.strip()
        if not source_kind or not source_session_id:
            raise ValidationError(
                "--source-kind and --source-session-id cannot be empty")
        return source_kind, source_session_id
    # Default-on provenance: agent runtimes inject their session identity into
    # the environment (DSH provides DSH_SESSION_ID).
    session_id = os.environ.get("DSH_SESSION_ID", "").strip()
    return ("dsh", session_id) if session_id else (None, None)


def cmd_open(args: argparse.Namespace) -> None:
    try:
        saved = read_mapping(args.document_id)
    except FileNotFoundError:
        saved = {}
    if saved.get("url"):
        print(canonical_review_url({"review_url": saved["url"]}))
        return
    print(canonical_review_url(_client().status(args.document_id)))


def cmd_status(args: argparse.Namespace) -> None:
    payload = _client().status(args.document_id)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    for key, value in payload.items():
        if key in ACCESS_KEYS:
            continue
        print(f"{key}: {value}")


def cmd_server_info(args: argparse.Namespace) -> None:
    client = _client()
    payload = {"health": client.health,
               "ready": client.ready,
               "version": client.version_info}[args.kind]()
    print(json.dumps(payload, indent=2, sort_keys=True))


def cmd_workspaces(args: argparse.Namespace) -> None:
    payload = _client().workspaces()
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    for ws in payload.get("workspaces", []):
        print(f"{ws.get('workspace_id')}\t{ws.get('workspace_name')}\t"
              f"[{ws.get('workspace_type')}]\t{ws.get('role')}")


def cmd_documents(args: argparse.Namespace) -> None:
    payload = _client().dashboard(args.workspace_id or "")
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    for doc in payload.get("reviews", []):
        status = doc.get("lifecycle_status") or ""
        print(f"{doc.get('document_id')}\t{doc.get('title')}\t"
              f"[{status}]\t{doc.get('unresolved_count')} open")


def cmd_search(args: argparse.Namespace) -> None:
    try:
        payload = search_documents(
            _client(), args.query, workspace_id=args.workspace_id or "",
            limit=args.limit, archived=args.archived,
            include_content=args.include_content)
    except ValidationError as exc:
        raise SystemExit(str(exc)) from exc
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    for doc in payload.get("matches", []):
        print(f"{doc.get('document_id')}\t{doc.get('title')}\t"
              f"[{doc.get('match_field')}]\t{doc.get('snippet')}")


def cmd_doctor(args: argparse.Namespace) -> None:
    cfg = _load_config()
    report = doctor_report(
        _client(), _server_url(), _automation_key(cfg),
        os.environ.get("REVISO_WORKSPACE_ID", cfg.get("workspace_id", "")))
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
        return
    print_doctor(report)


def cmd_packet(args: argparse.Namespace) -> None:
    v = "2" if args.v2 else "3"
    packet = _client().packet(args.document_id, args.thread_id, version=v)
    pid = packet.get("document_id", args.document_id)
    path = packet_path(f"pkt_{pid}", "json")
    write_json(path, packet)
    print(str(path))


def _workspace_scope(explicit: str = "", parent_id: str = ""):
    cfg = _load_config()
    key = _automation_key(cfg)
    return resolve_agent_create_scope(
        explicit_workspace_id=explicit, explicit_parent_id=parent_id,
        config=cfg, dsh_workspace_id=dsh_workspace(),
        has_automation_key=bool(key))


def _add_basic(sub: argparse._SubParsersAction) -> None:
    auth = sub.add_parser("auth")
    auth.add_argument("action", nargs="?", default="login", choices=["login", "status", "logout"])
    auth.add_argument("--server")
    auth.add_argument("--key")
    auth.add_argument("--no-browser", action="store_true", help="Print the login URL without opening a browser.")
    auth.set_defaults(func=cmd_auth)
    pub = sub.add_parser("publish")
    pub.add_argument("file")
    pub.add_argument("--title")
    pub.add_argument("--format", choices=["markdown", "md", "html"])
    pub.add_argument("--description", default="Initial draft")
    pub.add_argument("--workspace-id", default="")
    pub.add_argument("--parent-id", default="")
    pub.add_argument("--kind", choices=["document", "html_deck"])
    pub.add_argument("--deck-contract-version")
    pub.add_argument("--source-kind", help="Provenance channel tag, e.g. 'dsh' for a DeepSeek Harness session.")
    pub.add_argument("--no-source-binding", action="store_true", help="Skip the default session binding when the environment carries an agent session id.")
    pub.add_argument("--source-session-id", help="Session id within the source channel; enables session-scoped reads on the server.")
    pub.add_argument("--json", action="store_true", help="Print document_id, version_id, workspace_id, and review_url as JSON.")
    pub.add_argument("--no-upload-images", action="store_true",
                     help="Publish embedded data:image URIs unchanged.")
    pub.add_argument("--dry-run", action="store_true",
                     help="Report embedded image counts and bytes without publishing.")
    pub.set_defaults(func=cmd_publish)
    opn = sub.add_parser("open")
    opn.add_argument("document_id")
    opn.set_defaults(func=cmd_open)
    st = sub.add_parser("status")
    st.add_argument("document_id")
    st.add_argument("--json", action="store_true")
    st.set_defaults(func=cmd_status)
    wss = sub.add_parser("workspaces")
    wss.add_argument("--json", action="store_true")
    wss.set_defaults(func=cmd_workspaces)
    docs = sub.add_parser("documents")
    docs.add_argument("--workspace-id", default="")
    docs.add_argument("--json", action="store_true")
    docs.set_defaults(func=cmd_documents)
    search = sub.add_parser("search")
    search.add_argument("query")
    search.add_argument("--workspace-id", default="")
    search.add_argument("--limit", type=int, default=10)
    search.add_argument("--archived", action="store_true")
    search.add_argument("--include-content", action="store_true")
    search.add_argument("--json", action="store_true")
    search.set_defaults(func=cmd_search)
    doctor = sub.add_parser("doctor")
    doctor.add_argument("--json", action="store_true")
    doctor.set_defaults(func=cmd_doctor)
    for name in ("health", "ready", "version"):
        srv = sub.add_parser(name)
        srv.set_defaults(func=cmd_server_info, kind=name)


def _add_packet(sub: argparse._SubParsersAction) -> None:
    pkt = sub.add_parser("packet")
    pkt.add_argument("document_id")
    pkt.add_argument("--format", choices=["json"], default="json")
    pkt.add_argument("--thread-id", action="append")
    pkt.add_argument("--v2", action="store_true",
                     help="Use legacy packet v2 with sections")
    pkt.set_defaults(func=cmd_packet)


def _add_review_io(sub: argparse._SubParsersAction) -> None:
    exp = sub.add_parser("export")
    exp.add_argument("document_id")
    exp.add_argument("--output", default="")
    exp.set_defaults(func=cmd_export)
    imp = sub.add_parser("import")
    imp.add_argument("file")
    imp.add_argument("--workspace-id", default="")
    imp.add_argument("--parent-id", default="")
    imp.set_defaults(func=cmd_import)


def cmd_export(args: argparse.Namespace) -> None:
    bundle = _client().export_review(args.document_id)
    if args.output:
        write_json(Path(args.output), bundle)
        print(args.output)
        return
    print(json.dumps(bundle, indent=2, sort_keys=True))


def cmd_import(args: argparse.Namespace) -> None:
    bundle = read_json(Path(args.file))
    scope = _workspace_scope(args.workspace_id or "", args.parent_id or "")
    result = _client().import_review(
        bundle, scope.workspace_id, scope.parent_id)
    print(json.dumps(result, indent=2, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="reviso")
    sub = parser.add_subparsers(dest="cmd", required=True)
    _add_basic(sub)
    _add_packet(sub)
    _add_review_io(sub)
    add_guest_comment_commands(sub, _client)
    add_invite_commands(sub, _client)
    add_version_commands(sub, _client)
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except ValidationError as exc:
        raise SystemExit(str(exc)) from exc
