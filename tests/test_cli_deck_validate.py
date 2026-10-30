import json

import pytest

from reviso_cli.cli.deck import read_deck, DEFAULT_CONTRACT_VERSION
from reviso_cli.errors import ValidationError

DECK = (
    '<div class="hr-deck" data-aspect-ratio="16:9" '
    'data-contract-version="html-deck/1">'
    '<section class="hr-slide" data-slide-id="s01"><h1>Hi</h1></section>'
    '</div>'
)


class _Client:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def validate_deck(self, content, **kwargs):
        self.calls.append((content, kwargs))
        return self.result


class _Args:
    def __init__(self, file, client, json_output=False):
        self.file = str(file)
        self.client_factory = lambda: client
        self.json = json_output


def test_read_deck_reads_content_and_contract_version(tmp_path):
    path = tmp_path / 'deck.html'
    path.write_text(DECK)
    content, version = read_deck(str(path))
    assert content == DECK
    assert version == 'html-deck/1'


def test_read_deck_defaults_the_version_when_the_root_omits_it(tmp_path):
    path = tmp_path / 'deck.html'
    path.write_text(DECK.replace(' data-contract-version="html-deck/1"', ''))
    _, version = read_deck(str(path))
    assert version == DEFAULT_CONTRACT_VERSION


def test_read_deck_rejects_a_file_without_a_deck_root(tmp_path):
    # Sending a plain document to the deck gate wastes a round trip; the CLI can
    # tell locally that there is nothing to validate.
    path = tmp_path / 'not-a-deck.html'
    path.write_text('<div><p>hello</p></div>')
    with pytest.raises(ValidationError, match='not a deck'):
        read_deck(str(path))


def test_read_deck_rejects_a_missing_file(tmp_path):
    with pytest.raises(ValidationError, match='no such file'):
        read_deck(str(tmp_path / 'absent.html'))


def test_validate_sends_the_parsed_contract_version(tmp_path, capsys):
    from reviso_cli.cli.deck import cmd_deck_validate

    path = tmp_path / 'deck.html'
    path.write_text(DECK)
    client = _Client({'status': 'pass', 'diagnostics': [], 'elapsed_ms': 5})

    cmd_deck_validate(_Args(path, client))

    content, kwargs = client.calls[0]
    assert content == DECK
    assert kwargs['deck_contract_version'] == 'html-deck/1'
    assert 'pass' in capsys.readouterr().out


def test_failed_validation_exits_non_zero_but_still_prints_diagnostics(tmp_path, capsys):
    from reviso_cli.cli.deck import cmd_deck_validate

    path = tmp_path / 'deck.html'
    path.write_text(DECK)
    client = _Client({'status': 'fail', 'diagnostics': [
        {'code': 'deck_missing_slides', 'message': 'no slides',
         'fix_hint': 'add a section.hr-slide', 'slide_id': '', 'line': 0},
    ]})

    with pytest.raises(SystemExit) as exit_info:
        cmd_deck_validate(_Args(path, client))

    assert exit_info.value.code == 1
    out = capsys.readouterr().out
    assert 'fail' in out
    assert 'deck_missing_slides' in out
    assert 'add a section.hr-slide' in out


def test_json_output_is_the_raw_server_result(tmp_path, capsys):
    from reviso_cli.cli.deck import cmd_deck_validate

    path = tmp_path / 'deck.html'
    path.write_text(DECK)
    payload = {'status': 'pass', 'diagnostics': [], 'artifacts': [], 'elapsed_ms': 7}
    cmd_deck_validate(_Args(path, _Client(payload), json_output=True))
    assert json.loads(capsys.readouterr().out) == payload


def test_parser_exposes_deck_validate():
    from reviso_cli.cli import build_parser

    args = build_parser().parse_args(['deck', 'validate', 'a.html', '--json'])
    assert args.cmd == 'deck'
    assert args.deck_cmd == 'validate'
    assert args.json is True
