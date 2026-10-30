"""`reviso documents` and `reviso document archive|restore`.

The client and the server already supported paging and the recycle bin; the
command never exposed them, so a user with more documents than one page simply
could not see the rest, and archiving required dropping into the Python client.
"""
import json

import pytest

from reviso_cli.cli import build_parser


class _Client:
    def __init__(self, *, dashboard=None, write=None):
        self._dashboard = dashboard or {"reviews": []}
        self._write = write or {}
        self.dashboard_calls = []
        self.write_calls = []

    def dashboard(self, workspace_id="", limit=0, offset=0, archived=False):
        self.dashboard_calls.append(
            {"workspace_id": workspace_id, "limit": limit,
             "offset": offset, "archived": archived})
        return self._dashboard

    def archive(self, document_id):
        self.write_calls.append(("archive", document_id))
        return self._write

    def restore(self, document_id):
        self.write_calls.append(("restore", document_id))
        return self._write


def _run(argv, client):
    args = build_parser().parse_args(argv)
    # The command bodies call module-level _client(); swap it in so the test
    # exercises the real argument plumbing rather than a stub parser.
    import reviso_cli.cli as cli_module
    original = cli_module._client
    cli_module._client = lambda: client
    try:
        args.func(args)
    finally:
        cli_module._client = original


def test_documents_passes_paging_and_archived_to_the_client(capsys):
    client = _Client()
    _run(["documents", "--workspace-id", "wsp_1", "--limit", "5",
          "--offset", "10", "--archived"], client)
    assert client.dashboard_calls == [
        {"workspace_id": "wsp_1", "limit": 5, "offset": 10, "archived": True}]


def test_documents_prints_the_next_page_hint(capsys):
    client = _Client(dashboard={
        "reviews": [{"document_id": "doc_a", "title": "A",
                     "lifecycle_status": "active", "unresolved_count": 0}],
        "has_more": True, "next_offset": 50,
    })
    _run(["documents"], client)
    out = capsys.readouterr().out
    assert "--offset 50" in out


def test_documents_json_is_the_raw_payload(capsys):
    payload = {"reviews": [], "has_more": False, "next_offset": None}
    _run(["documents", "--json"], _Client(dashboard=payload))
    assert json.loads(capsys.readouterr().out) == payload


def test_archive_invokes_the_client_and_reports(capsys):
    client = _Client(write={"document_id": "doc_1", "lifecycle_status": "archived"})
    _run(["document", "archive", "doc_1"], client)
    assert client.write_calls == [("archive", "doc_1")]
    assert "archived doc_1" in capsys.readouterr().out


def test_restore_invokes_the_client_and_reports(capsys):
    client = _Client(write={"document_id": "doc_1", "lifecycle_status": "active"})
    _run(["document", "restore", "doc_1"], client)
    assert client.write_calls == [("restore", "doc_1")]
    assert "restored doc_1" in capsys.readouterr().out


def test_documents_rejects_a_non_integer_limit():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["documents", "--limit", "many"])
