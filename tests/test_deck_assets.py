from __future__ import annotations

import base64

import pytest

from reviso_cli.deck_assets import asset_request, find_images, payload_summary, rewrite


PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"x" * 20).decode()


def _deck(src: str) -> str:
    return f'<section><img src="{src}" alt="x"></section>'


def test_find_and_rewrite_preserves_surrounding_html():
    image_uri = f"data:image/png;base64,{PNG}"
    deck = _deck(image_uri)
    images = find_images(deck)
    assert len(images) == 1
    out = rewrite(deck, [(images[0], "/api/documents/doc_1/assets/ast_1")])
    assert out == _deck("/api/documents/doc_1/assets/ast_1")
    assert "data:image/" not in out


def test_summary_counts_encoded_and_remaining_bytes():
    images = find_images(_deck(f"data:image/png;base64,{PNG}"))
    summary = payload_summary(_deck(f"data:image/png;base64,{PNG}"))
    assert summary["image_count"] == 1
    assert summary["decoded_bytes"] == len(images[0].decoded)
    assert summary["remaining_bytes"] < len(_deck(images[0].data_uri))


def test_invalid_or_unsupported_uri_is_not_removed():
    deck = _deck("data:image/svg+xml;base64,PHN2Zz4=")
    assert find_images(deck) == []
    assert rewrite(deck, []) == deck


def test_rewrite_rejects_mismatched_upload_count():
    image = find_images(_deck(f"data:image/png;base64,{PNG}"))[0]
    with pytest.raises(ValueError, match="upload count"):
        rewrite(_deck(image.data_uri), [])


def test_asset_request_requires_operation_id():
    image = find_images(_deck(f"data:image/png;base64,{PNG}"))[0]
    with pytest.raises(ValueError, match="operation_id"):
        asset_request(image, file_name="slide.png", operation_id="")
