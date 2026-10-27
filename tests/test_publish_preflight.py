"""Publish size preflight: the CLI measures the same JSON body the server will."""
from __future__ import annotations

import json

import pytest

from reviso_cli.cli.preflight import (
    MAX_PUBLISH_JSON_BYTES,
    check_publish_size,
    max_publish_json_bytes,
)
from reviso_cli.client import publish_request_body
from reviso_cli.errors import ValidationError

MB = 1024 * 1024


def body(content: str) -> dict:
    return publish_request_body("title", content)


def test_default_limit_matches_server_ceiling():
    assert MAX_PUBLISH_JSON_BYTES == 37748736
    assert max_publish_json_bytes({}) == MAX_PUBLISH_JSON_BYTES


@pytest.mark.parametrize("raw", ["abc", "0", "-5", "", "1.5"])
def test_invalid_or_non_positive_limit_falls_back_to_default(raw):
    assert max_publish_json_bytes({"REVISO_MAX_PUBLISH_JSON_BYTES": raw}) == MAX_PUBLISH_JSON_BYTES


def test_env_override_parses_positive_int():
    env = {"REVISO_MAX_PUBLISH_JSON_BYTES": " 2048 "}
    assert max_publish_json_bytes(env) == 2048


def test_under_limit_body_passes():
    check_publish_size(body("small draft"), {"REVISO_MAX_PUBLISH_JSON_BYTES": str(MB)})


def test_over_limit_error_names_actual_and_limit_sizes():
    limit = 2 * MB
    with pytest.raises(ValidationError) as exc:
        check_publish_size(body("x" * (3 * MB)), {"REVISO_MAX_PUBLISH_JSON_BYTES": str(limit)})
    message = str(exc.value)
    assert "3.0 MB" in message
    assert "2.0 MB" in message
    assert "REVISO_MAX_PUBLISH_JSON_BYTES" in message
    assert "images" in message  # one concrete reduction suggestion


def test_preflight_measures_the_bytes_the_client_sends():
    # request_json sends json.dumps(body).encode("utf-8"); a limit of exactly
    # that many bytes must pass, and one byte less must fail.
    payload = body("x" * 100)
    exact = len(json.dumps(payload).encode("utf-8"))
    env = {"REVISO_MAX_PUBLISH_JSON_BYTES": str(exact)}
    check_publish_size(payload, env)
    with pytest.raises(ValidationError):
        check_publish_size(payload, {**env, "REVISO_MAX_PUBLISH_JSON_BYTES": str(exact - 1)})
