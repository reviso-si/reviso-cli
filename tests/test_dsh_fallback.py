# ruff: noqa: S105  # credential fixtures, never real tokens
"""DSH host credential fallback: token, server, and workspace resolution."""
from __future__ import annotations

import os
from datetime import datetime

import pytest

from reviso_cli import cli
from reviso_cli.cli import credentials
from reviso_cli.cli.dsh_credentials import (
    EXPIRES_REF,
    dsh_expires_at,
    dsh_token_expired,
    read_dsh_refs,
)

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
    path = dsh_dir / ".credentials.yaml"
    path.write_text("\n".join(lines) + "\n")
    # The host writes the file owner-only; the CLI reader refuses anything looser.
    os.chmod(path, 0o600)


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
    path = dsh / ".credentials.yaml"
    path.write_text("refs: [broken, flow\n")
    os.chmod(path, 0o600)
    assert read_dsh_refs() == {}
    assert read_dsh_refs(dsh / "absent.yaml") == {}


def test_dsh_expires_at_parses_the_host_formats():
    # The host records epoch ms and its YAML writer may quote the number.
    assert dsh_expires_at({EXPIRES_REF: '"1793096914950"'}) == pytest.approx(1793096914.950)
    assert dsh_expires_at({EXPIRES_REF: "1793096914950"}) == pytest.approx(1793096914.95)
    assert dsh_expires_at({}) is None


@pytest.mark.parametrize("raw", ["", "abc", "1e999", "-1", "0", "nan", "1e30"])
def test_malformed_expiry_is_treated_as_absent(raw):
    assert dsh_expires_at({EXPIRES_REF: raw}) is None
    assert not dsh_token_expired({EXPIRES_REF: raw})


def test_dsh_token_expired_uses_the_recorded_millisecond_boundary():
    refs = {EXPIRES_REF: '"1500000000000"'}  # 1500000000.0 s
    assert not dsh_token_expired(refs, now=1499999999.999)
    assert dsh_token_expired(refs, now=1500000000.0)


def test_expired_dsh_token_is_skipped_and_explained(tmp_path):
    write_dsh_file(tmp_path / ".dsh", {**DSH_FILE, EXPIRES_REF: '"1000000000000"'})
    assert credentials.dsh_token("https://reviso.test") == ""
    with pytest.raises(SystemExit) as exc:
        cli._automation_key({})
    message = str(exc.value)
    assert "https://reviso.test" in message  # the recorded REVISO_DSH_SERVER
    assert str(tmp_path / ".dsh" / ".credentials.yaml") in message
    expected = datetime.fromtimestamp(1e9).astimezone().isoformat(timespec="seconds")
    assert expected in message  # expiry as ISO local time
    assert "Reconnect the Reviso connection in DSH" in message
    assert "REVISO_AUTOMATION_KEY" in message


def test_future_dsh_expiry_still_falls_back(tmp_path):
    write_dsh_file(tmp_path / ".dsh", {**DSH_FILE, EXPIRES_REF: '"4000000000000"'})
    assert cli._automation_key({}) == "dsh-test-token"


def test_missing_expiry_field_still_falls_back(tmp_path):
    write_dsh_file(tmp_path / ".dsh", DSH_FILE)
    assert cli._automation_key({}) == "dsh-test-token"


@pytest.mark.parametrize("raw", ['"not-a-number"', '""', '"abc123"'])
def test_malformed_expiry_keeps_the_fallback_alive(tmp_path, raw):
    write_dsh_file(tmp_path / ".dsh", {**DSH_FILE, EXPIRES_REF: raw})
    assert cli._automation_key({}) == "dsh-test-token"


def test_world_readable_dsh_file_is_ignored_with_one_warning(tmp_path, capsys):
    dsh = tmp_path / ".dsh"
    write_dsh_file(dsh, DSH_FILE)
    os.chmod(dsh / ".credentials.yaml", 0o644)
    assert read_dsh_refs() == {}
    assert read_dsh_refs() == {}  # repeated reads do not repeat the warning
    err = capsys.readouterr().err
    assert err.count("ignoring DSH host credential file") == 1
    assert "0600" in err
    assert "dsh-test-token" not in err  # contents are never printed


def test_non_regular_dsh_file_is_ignored(tmp_path, capsys):
    dsh = tmp_path / ".dsh"
    dsh.mkdir()
    (dsh / ".credentials.yaml").mkdir()
    assert read_dsh_refs() == {}
    assert "not a regular file" in capsys.readouterr().err


def test_empty_or_oversized_dsh_file_is_ignored(tmp_path, capsys):
    dsh = tmp_path / ".dsh"
    dsh.mkdir()
    empty = dsh / ".credentials.yaml"
    empty.write_text("")
    os.chmod(empty, 0o600)
    assert read_dsh_refs() == {}
    big_dir = tmp_path / "big-dsh"
    big_dir.mkdir()
    big = big_dir / ".credentials.yaml"
    big.write_text("x" * (1024 * 1024 + 1))
    os.chmod(big, 0o600)
    assert read_dsh_refs(big) == {}
    err = capsys.readouterr().err
    assert err.count("outside the accepted range") == 2
    assert "xxxxx" not in err  # contents are never printed


@pytest.mark.skipif(not hasattr(os, "getuid"), reason="POSIX-only check")
def test_foreign_owned_dsh_file_is_ignored(tmp_path, monkeypatch):
    write_dsh_file(tmp_path / ".dsh", DSH_FILE)
    real = os.getuid()
    monkeypatch.setattr(os, "getuid", lambda: real + 1)
    assert read_dsh_refs() == {}
