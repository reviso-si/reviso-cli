# ruff: noqa: S105  # credential fixtures, never real tokens
"""DSH host credential fallback: token, server, and workspace resolution."""
from __future__ import annotations

import pytest

from reviso_cli import cli
from reviso_cli.cli.dsh_credentials import read_dsh_refs

DSH_FILE = {
    "REVISO_DSH_TOKEN": "dsh-test-token",
    "REVISO_DSH_SERVER": "https://reviso.test",
    "REVISO_DSH_WORKSPACE_ID": "ws_dsh_test",
}


def write_dsh_file(dsh_dir, refs: dict[str, str], extra: str = "") -> None:
    # $DSH_HOME (or ~/.dsh) IS the credential directory; the file sits inside it.
    dsh_dir.mkdir(parents=True, exist_ok=True)
    lines = ["version: 1", "refs:"]
    lines.extend(f"  {key}: {value}" for key, value in refs.items())
    if extra:
        lines.extend(extra.splitlines())
    (dsh_dir / ".credentials.yaml").write_text("\n".join(lines) + "\n")


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("REVISO_STATE_DIR", str(tmp_path / "state"))
    for name in ("REVISO_SERVER", "REVISO_AUTOMATION_KEY", "REVISO_WORKSPACE_ID", "DSH_HOME"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))


def test_dsh_file_resolves_token_server_and_workspace(monkeypatch, tmp_path):
    write_dsh_file(tmp_path / ".dsh", DSH_FILE)
    assert cli._server_url() == "https://reviso.test"
    assert cli._automation_key({}) == "dsh-test-token"
    scope = cli._workspace_scope("", "")
    assert scope.workspace_id == "ws_dsh_test"
    assert scope.source == "dsh_host"


def test_environment_key_still_wins_over_dsh_file(monkeypatch, tmp_path):
    write_dsh_file(tmp_path / ".dsh", DSH_FILE)
    monkeypatch.setenv("REVISO_AUTOMATION_KEY", "env-key")
    assert cli._automation_key({}) == "env-key"


def test_workspace_argument_and_env_beat_dsh_file(monkeypatch, tmp_path):
    write_dsh_file(tmp_path / ".dsh", DSH_FILE)
    assert cli._workspace_scope("ws_arg", "").workspace_id == "ws_arg"
    monkeypatch.setenv("REVISO_WORKSPACE_ID", "ws_env")
    assert cli._workspace_scope("", "").source == "env"


def test_missing_dsh_file_keeps_existing_behavior(monkeypatch, tmp_path):
    assert cli._automation_key({}) == ""
    assert cli._server_url() == "https://reviso.work"
    with pytest.raises(SystemExit, match="workspace_id required"):
        cli._workspace_scope("", "")


def test_dsh_token_is_not_reused_on_another_origin(monkeypatch, tmp_path):
    write_dsh_file(tmp_path / ".dsh", DSH_FILE)
    monkeypatch.setenv("REVISO_SERVER", "https://other.test")
    assert cli._server_url() == "https://other.test"
    assert cli._automation_key({}) == ""


def test_dsh_home_overrides_the_directory(monkeypatch, tmp_path):
    write_dsh_file(tmp_path / "custom-dsh", DSH_FILE)
    monkeypatch.setenv("DSH_HOME", str(tmp_path / "custom-dsh"))
    assert cli._server_url() == "https://reviso.test"
    assert cli._automation_key({}) == "dsh-test-token"


def test_token_without_server_ref_pairs_with_the_default_origin(tmp_path):
    write_dsh_file(tmp_path / ".dsh", {"REVISO_DSH_TOKEN": "dsh-default-token"})
    assert cli._server_url() == "https://reviso.work"
    assert cli._automation_key({}) == "dsh-default-token"


def test_records_section_is_never_read(tmp_path):
    extra = "\n".join([
        "records:",
        "  rec_1:",
        "    kind: secret",
        "    payload:",
        "      version: 1",
        "      REVISO_DSH_TOKEN: decoy-token",
        "      secret: ignored",
    ])
    write_dsh_file(tmp_path / ".dsh", DSH_FILE, extra)
    assert read_dsh_refs()["REVISO_DSH_TOKEN"] == "dsh-test-token"


def test_unreadable_or_malformed_file_yields_no_refs(tmp_path):
    dsh = tmp_path / ".dsh"
    dsh.mkdir()
    (dsh / ".credentials.yaml").write_text("refs: [broken, flow\n")
    assert read_dsh_refs() == {}
    assert read_dsh_refs(dsh / "absent.yaml") == {}
