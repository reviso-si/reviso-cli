"""Client behaviour against a fake server.

These pin the contract the agent skill depends on: what path a call hits, that
the base version is actually sent, and that a server error envelope surfaces as
a coded failure rather than a bare stack trace.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from reviso_cli.client import RevisoClient


class _Recorder(BaseHTTPRequestHandler):
    calls: list = []

    def _handle(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length).decode() if length else ""
        type(self).calls.append({
            "method": self.command,
            "path": self.path,
            "authorization": self.headers.get("Authorization"),
            "body": json.loads(raw) if raw else None,
        })
        status, payload = self.server.response  # type: ignore[attr-defined]
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = _handle
    do_POST = _handle

    def log_message(self, *args) -> None:  # keep pytest output clean
        pass


@pytest.fixture()
def server():
    _Recorder.calls = []
    httpd = HTTPServer(("127.0.0.1", 0), _Recorder)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd
    finally:
        httpd.shutdown()
        thread.join(timeout=5)


def _client(httpd) -> RevisoClient:
    host, port = httpd.server_address
    return RevisoClient(f"http://{host}:{port}", "rak_test")


def test_publish_posts_body_and_returns_response(server):
    server.response = (200, {"document_id": "doc_1", "browser_url": "https://x/d"})
    result = _client(server).publish(
        "Title", "# Body", "markdown", "Initial draft", "wsp_1", "")
    assert result["document_id"] == "doc_1"
    call = _Recorder.calls[-1]
    assert call["method"] == "POST"
    assert call["path"] == "/api/documents"
    assert call["authorization"] == "Bearer rak_test"
    assert call["body"]["title"] == "Title"
    assert call["body"]["workspace_id"] == "wsp_1"


def test_update_always_carries_the_base_version(server):
    server.response = (200, {"version_id": "ver_2"})
    _client(server).update("doc_1", "# Body", "ver_1", "Fix typo")
    call = _Recorder.calls[-1]
    assert call["path"] == "/api/documents/doc_1/agent-update"
    assert call["body"]["base_version_id"] == "ver_1"


def test_server_error_envelope_becomes_a_coded_failure(server):
    server.response = (409, {"error": {"code": "CAS_CONFLICT",
                                       "message": "base_version_changed"}})
    with pytest.raises(SystemExit) as excinfo:
        _client(server).update("doc_1", "# Body", "ver_stale", "Fix typo")
    assert "CAS_CONFLICT" in str(excinfo.value)


def test_client_has_no_share_link_surface():
    """Share-link creation needs the server's access mapping, which this
    repository deliberately does not ship."""
    client = RevisoClient("https://example.test", "rak_test")
    for name in ("create_share_link", "list_share_links", "revoke_share_link"):
        assert not hasattr(client, name)
    assert hasattr(client, "create_invite")
