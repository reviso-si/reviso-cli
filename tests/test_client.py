"""Client behaviour against a fake server.

These pin the contract the agent skill depends on: what path a call hits, that
the base version is actually sent, that a server error envelope surfaces as a
coded failure, and that a redirect cannot walk the credential off-origin.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from reviso_cli.client import RevisoClient

DEFAULT = "*"


class _Recorder(BaseHTTPRequestHandler):
    def _handle(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length).decode() if length else ""
        server = self.server
        server.calls.append({  # type: ignore[attr-defined]
            "method": self.command,
            "path": self.path,
            "authorization": self.headers.get("Authorization"),
            "body": json.loads(raw) if raw else None,
        })
        status, payload, location = server.routes.get(  # type: ignore[attr-defined]
            self.path, server.routes[DEFAULT])
        body = json.dumps(payload).encode()
        self.send_response(status)
        if location:
            self.send_header("Location", location)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = _handle
    do_POST = _handle

    def log_message(self, *args) -> None:  # keep pytest output clean
        pass


def _serve(**routes):
    """Start a fake server. Routes map a path to (status, payload, location)."""
    httpd = HTTPServer(("127.0.0.1", 0), _Recorder)
    httpd.calls = []  # type: ignore[attr-defined]
    httpd.routes = {DEFAULT: (200, {}, "")}  # type: ignore[attr-defined]
    for path, spec in routes.items():
        httpd.routes["/" if path == "root" else path] = spec  # type: ignore[attr-defined]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, thread


def _stop(httpd, thread) -> None:
    httpd.shutdown()
    thread.join(timeout=5)


@pytest.fixture()
def server():
    httpd, thread = _serve()
    try:
        yield httpd
    finally:
        _stop(httpd, thread)


def _client(httpd) -> RevisoClient:
    host, port = httpd.server_address
    return RevisoClient(f"http://{host}:{port}", "rak_test")


def test_publish_posts_body_and_returns_response(server):
    server.routes["/api/documents"] = (
        200, {"document_id": "doc_1", "browser_url": "https://x/d"}, "")
    result = _client(server).publish(
        "Title", "# Body", "markdown", "Initial draft", "wsp_1", "")
    assert result["document_id"] == "doc_1"
    call = server.calls[-1]
    assert call["method"] == "POST"
    assert call["path"] == "/api/documents"
    assert call["authorization"] == "Bearer rak_test"
    assert call["body"]["title"] == "Title"
    assert call["body"]["workspace_id"] == "wsp_1"


def test_update_always_carries_the_base_version(server):
    server.routes["/api/documents/doc_1/agent-update"] = (200, {"version_id": "ver_2"}, "")
    _client(server).update("doc_1", "# Body", "ver_1", "Fix typo")
    call = server.calls[-1]
    assert call["path"] == "/api/documents/doc_1/agent-update"
    assert call["body"]["base_version_id"] == "ver_1"


def test_server_error_envelope_becomes_a_coded_failure(server):
    server.routes["/api/documents/doc_1/agent-update"] = (
        409, {"error": {"code": "CAS_CONFLICT", "message": "base_version_changed"}}, "")
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


def test_cross_origin_redirect_never_reaches_the_other_host(server):
    """A redirect off-origin must not carry the automation key with it.

    urllib follows redirects by default and replays the request headers, so
    without the guard the second server receives the Authorization header. The
    assertion that matters is the second one: zero calls arrived there.
    """
    other, other_thread = _serve()
    try:
        host, port = other.server_address
        server.routes["/healthz"] = (
            302, {"error": {"code": "MOVED"}}, f"http://{host}:{port}/steal")

        with pytest.raises(SystemExit) as excinfo:
            _client(server).health()

        assert "cross-origin redirect refused" in str(excinfo.value)
        assert other.calls == []
    finally:
        _stop(other, other_thread)


def test_same_origin_redirect_is_still_followed(server):
    """The guard must not break an ordinary redirect on the same origin."""
    server.routes["/healthz"] = (302, {"error": {"code": "MOVED"}}, "/moved")
    server.routes["/moved"] = (200, {"status": "ok"}, "")

    assert _client(server).health() == {"status": "ok"}
    assert [call["path"] for call in server.calls] == ["/healthz", "/moved"]
    assert server.calls[-1]["authorization"] == "Bearer rak_test"


@pytest.mark.parametrize("existing", [False, True])
def test_invite_cli_formats_account_share_without_invite_id(server, existing, capsys):
    from argparse import Namespace
    from reviso_cli.cli.invites import _create

    server.routes["/api/documents/doc_1/invites"] = (
        200 if existing else 201,
        {"account_shared": True, "review_id": "doc_1", "grant_id": "test-grant", "existing": existing}, "")
    _create(Namespace(document_id="doc_1", email="reader@example.test", access="comment", json=False),
            lambda: _client(server))
    label = "account share updated" if existing else "shared with account"
    assert capsys.readouterr().out.strip() == f"{label}: test-grant"
    assert server.calls[-1]["body"] == {"email": "reader@example.test", "access": "comment"}
