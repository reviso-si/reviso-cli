"""`reviso publish` must surface the server's duplicate-title hint.

The server computes ``duplicate_title_hint`` when a session already holds a
document with this exact title, and the title helper may suffix the new one with
``(1)``..``(9)``. The CLI used to drop both, so an agent creating documents in a
loop produced eleven near-identical entries and never saw why.
"""
import json

import reviso_cli.cli as cli


class _Client:
    def __init__(self, result):
        self._result = result
        self.published = []

    def publish(self, title, content, fmt, description, workspace_id,
                parent_id, **kwargs):
        self.published.append({"title": title, "kwargs": kwargs})
        return self._result


def _run_publish(tmp_path, monkeypatch, *, result, argv_extra=()):
    deck = tmp_path / 'doc.md'
    deck.write_text('# hello\n')
    client = _Client(result)
    monkeypatch.setattr(cli, '_client', lambda: client)
    monkeypatch.setattr('reviso_cli.local.write_mapping', lambda *a, **k: {
        'document_id': 'doc_1', 'url': 'https://reviso.work/d/1',
        'base_server_version_id': 'ver_1',
    })
    monkeypatch.setattr(cli.command_journal, 'operation_id_for', lambda *a: 'op_1')
    monkeypatch.setattr(cli.command_journal, 'forget', lambda *a: None)
    monkeypatch.setattr(cli, 'check_publish_size', lambda *a, **k: None)
    args = cli.build_parser().parse_args(
        ['publish', str(deck), '--title', 'Same title', *argv_extra])
    args.func(args)
    return client


def test_json_output_carries_the_duplicate_hint(tmp_path, monkeypatch, capsys):
    result = {
        'document_id': 'doc_1', 'version_id': 'ver_1',
        'review_url': 'https://reviso.work/d/1',
        'duplicate_title_hint': {'document_id': 'doc_old', 'title': 'Same title (1)'},
    }
    _run_publish(tmp_path, monkeypatch, result=result, argv_extra=('--json',))
    payload = json.loads(capsys.readouterr().out)
    assert payload['duplicate_title_hint'] == {
        'document_id': 'doc_old', 'title': 'Same title (1)'}


def test_json_output_omits_the_key_when_there_is_no_hint(tmp_path, monkeypatch, capsys):
    _run_publish(tmp_path, monkeypatch,
                 result={'document_id': 'doc_1', 'version_id': 'ver_1',
                         'review_url': 'https://reviso.work/d/1'},
                 argv_extra=('--json',))
    payload = json.loads(capsys.readouterr().out)
    assert 'duplicate_title_hint' not in payload


def test_human_output_warns_on_stderr(tmp_path, monkeypatch, capsys):
    _run_publish(tmp_path, monkeypatch, result={
        'document_id': 'doc_1', 'version_id': 'ver_1',
        'review_url': 'https://reviso.work/d/1',
        'duplicate_title_hint': {'document_id': 'doc_old', 'title': 'Same title (1)'},
    })
    captured = capsys.readouterr()
    assert 'https://reviso.work/d/1' in captured.out
    assert 'already has this title' in captured.err
    assert 'doc_old' in captured.err
    assert 'Same title (1)' in captured.err


def test_warning_still_reads_sensibly_when_the_server_omits_a_title():
    message = cli._duplicate_title_warning({'document_id': 'doc_old'})
    assert 'already has this title' in message
    assert 'doc_old' in message
