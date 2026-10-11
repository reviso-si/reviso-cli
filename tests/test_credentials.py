# ruff: noqa: S105  # credential fixtures, never real tokens
"""Persistence, origin isolation and concurrent refresh through the real CLI path."""
import io
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from reviso_cli import cli
from reviso_cli.cli import credentials
from reviso_cli.cli.credential_file import credential_path, read_credentials
from reviso_cli.cli.oauth_http import OAuthFailure
from reviso_cli.client import http

SERVER = "https://reviso.test"


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("REVISO_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.delenv("REVISO_SERVER", raising=False)
    monkeypatch.delenv("REVISO_AUTOMATION_KEY", raising=False)
    def request(req, **kwargs):
        return io.BytesIO(json.dumps({"authorization": req.get_header("Authorization")}).encode())
    monkeypatch.setattr(http.urllib.request, "build_opener", lambda *a: SimpleNamespace(open=request))


def saved(**overrides):
    return {"access_token": "test-old", "refresh_token": "test-old", "client_id": "test-one",
            "expires_at": time.time() - 1, **overrides}


def fresh():
    return {"access_token": "test-new", "refresh_token": "test-new", "expires_in": 3600,
            "token_type": "Bearer", "refresh_expires_at": "2099-01-01T00:00:00Z"}


def test_login_survives_directory_change_and_never_prints_keys(monkeypatch, tmp_path, capsys):
    credentials.save_login(SERVER, saved(expires_at=time.time() + 3600))
    other = tmp_path / "another-project"
    other.mkdir()
    monkeypatch.chdir(other)
    assert cli._server_url() == SERVER
    assert cli._client().workspaces()["authorization"] == "Bearer test-old"
    cli.cmd_auth(cli.build_parser().parse_args(["auth", "status"]))
    assert "OAuth saved" in capsys.readouterr().out
    assert credential_path().stat().st_mode & 0o777 == 0o600


def test_expired_token_refresh_is_serialized(monkeypatch):
    credentials.save_login(SERVER, saved())
    calls = []

    def exchange(url, body, **kwargs):
        calls.append((url, body))
        time.sleep(0.1)
        return fresh()

    monkeypatch.setattr(credentials, "oauth_json", exchange)
    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(lambda _: cli._client().workspaces()["authorization"], range(5)))
    assert results == ["Bearer test-new"] * 5
    assert len(calls) == 1
    assert calls[0][1]["client_id"] == "test-one"
    assert calls[0][1]["resource"] == SERVER + "/mcp"
    assert read_credentials()["servers"][SERVER]["refresh_token"] == "test-new"


def test_ambiguous_refresh_is_not_replayed(monkeypatch):
    credentials.save_login(SERVER, saved())
    calls = []

    def unavailable(*args, **kwargs):
        calls.append(True)
        raise OAuthFailure("unavailable_or_invalid_response")

    monkeypatch.setattr(credentials, "oauth_json", unavailable)
    for _ in range(2):
        with pytest.raises(OAuthFailure):
            cli._client().workspaces()
    assert calls == [True]
    assert read_credentials()["servers"][SERVER]["reauth_required"]


def test_server_override_does_not_reuse_project_or_other_origin_key(monkeypatch):
    credentials.save_login(SERVER, saved(expires_at=time.time() + 3600))
    monkeypatch.setenv("REVISO_SERVER", "https://other.test")
    cfg = {"server": SERVER, "automation_key": "test-project"}
    assert credentials.access_token(credentials.selected_server(cfg), cfg) == ""
    monkeypatch.setenv("REVISO_AUTOMATION_KEY", "test-explicit")
    assert credentials.access_token("https://other.test", cfg) == "test-explicit"




def test_invalid_token_response_preserves_reauth_required(monkeypatch):
    credentials.save_login(SERVER, saved())
    monkeypatch.setattr(credentials, "oauth_json", lambda *a, **k: {"access_token": "test-new"})
    with pytest.raises(OAuthFailure, match="invalid_token_response"):
        cli._client().workspaces()
    assert read_credentials()["servers"][SERVER]["reauth_required"]


def test_world_readable_credentials_are_rejected():
    credentials.save_login(SERVER, saved())
    os.chmod(credential_path(), 0o644)
    with pytest.raises(ValueError, match="owner-only"):
        read_credentials()






def test_rate_limit_preserves_unused_refresh_for_retry(monkeypatch):
    credentials.save_login(SERVER, saved())

    def throttled(*args, **kwargs):
        raise OAuthFailure("rate_limited")

    monkeypatch.setattr(credentials, "oauth_json", throttled)
    with pytest.raises(OAuthFailure, match="rate_limited"):
        cli._client().workspaces()
    assert not read_credentials()["servers"][SERVER].get("reauth_required")
    monkeypatch.setattr(credentials, "oauth_json", lambda *a, **k: fresh())
    assert cli._client().workspaces()["authorization"] == "Bearer test-new"


def test_guest_and_public_requests_do_not_refresh_an_account_login(monkeypatch):
    credentials.save_login(SERVER, saved(reauth_required=True))
    client = cli._client()
    assert client.health()["authorization"] is None
    assert client.comment("doc_fixture", "guest_fixture", "guest_secret", "Review", {})["authorization"] is None
    with pytest.raises(OAuthFailure, match="login_required"):
        client.workspaces()


def test_old_server_oauth_token_remains_usable_until_advertised_expiry(monkeypatch):
    old = {"access_token": "test-legacy", "token_type": "Bearer", "expires_in": 31536000}
    entry = {"client_id": "test-legacy", **credentials.token_fields(old, require_refresh=False)}
    credentials.save_login(SERVER, entry)
    assert cli._client().workspaces()["authorization"] == "Bearer test-legacy"
    credentials.save_login(SERVER, {**entry, "expires_at": time.time() - 1})
    with pytest.raises(OAuthFailure, match="login_required"):
        cli._client().workspaces()
    with pytest.raises(OAuthFailure, match="invalid_token_response"):
        credentials.token_fields(old, require_refresh=True)


@pytest.mark.parametrize("server", ["", "http://127.0.0.1:5173"])
def test_key_login_validates_and_saves_selected_origin(monkeypatch, server):
    requests = []

    def request(req, **kwargs):
        requests.append((req.full_url, req.get_header("Authorization")))
        return io.BytesIO(b'{"connection_id":"key_fixture"}')

    monkeypatch.setattr(http.urllib.request, "build_opener", lambda *a: SimpleNamespace(open=request))
    args = cli.build_parser().parse_args(["auth", "login", "--key", "test-scoped", "--server", server])
    cli.cmd_auth(args)
    origin = server or "https://reviso.work"
    assert requests == [(origin + "/api/agent-connection/self", "Bearer test-scoped")]
    assert read_credentials()["server"] == origin
    assert read_credentials()["servers"][origin]["access_token"] == "test-scoped"



def test_mapping_uses_the_same_saved_origin_as_authenticated_commands(tmp_path):
    from reviso_cli.local import write_mapping

    credentials.save_login(SERVER, saved(expires_at=time.time() + 3600))
    source = tmp_path / 'draft.md'
    source.write_text('draft')
    mapping = write_mapping({'document_id': 'doc_aaaaaaaaaaaa', 'version_id': 'v1'}, source)
    assert mapping['url'] == SERVER + '/documents/aaaaaaaaaaaa'
