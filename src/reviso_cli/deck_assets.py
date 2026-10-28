"""Deterministic data-URI extraction and rewrite for HTML decks.

The server intentionally keeps a bounded inline-data budget.  This module makes
the recoverable path explicit: upload each embedded image, then replace only the
exact URI in the deck.  It has no HTTP or CLI dependencies so DSH and MCP can
share the same rules.
"""

from __future__ import annotations

import base64
import binascii
import re
from dataclasses import dataclass

_DATA_URI = re.compile(
    r"data:(image/(?:png|jpeg|gif|webp));base64,([A-Za-z0-9+/=]+)",
    re.IGNORECASE,
)
_ALLOWED = {"image/png", "image/jpeg", "image/gif", "image/webp"}
_MAX_DECODED = 5 * 1024 * 1024


@dataclass(frozen=True)
class EmbeddedImage:
    mime: str
    encoded: str
    decoded: bytes
    start: int
    end: int

    @property
    def data_uri(self) -> str:
        return f"data:{self.mime};base64,{self.encoded}"


def find_images(content: str) -> list[EmbeddedImage]:
    """Return valid supported image data URIs in source order.

    Invalid, unsupported, or oversized candidates remain in the HTML and are
    left to the existing deck validator/renderer to reject with its typed
    contract error.  Preprocessing must never silently remove content.
    """
    if not isinstance(content, str):
        raise TypeError("deck content must be a string")
    found: list[EmbeddedImage] = []
    for match in _DATA_URI.finditer(content):
        mime = match.group(1).lower()
        encoded = match.group(2)
        if mime not in _ALLOWED:
            continue
        try:
            decoded = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error):
            continue
        if not decoded or len(decoded) > _MAX_DECODED:
            continue
        found.append(EmbeddedImage(
            mime=mime, encoded=encoded, decoded=decoded,
            start=match.start(), end=match.end(),
        ))
    return found


def payload_summary(content: str) -> dict:
    images = find_images(content)
    return {
        "image_count": len(images),
        "encoded_bytes": sum(len(image.encoded) for image in images),
        "decoded_bytes": sum(len(image.decoded) for image in images),
        "largest_image_bytes": max((len(image.decoded) for image in images), default=0),
        "remaining_bytes": len(content.encode("utf-8")) - sum(
            len(image.data_uri.encode("utf-8")) for image in images),
    }


def rewrite(content: str, uploads: list[tuple[EmbeddedImage, str]]) -> str:
    """Replace each extracted URI with its server-returned asset URL.

    Rewriting from the original spans avoids replacing identical image bytes
    globally and is strict about stale/mismatched preprocessing input.
    """
    if len(uploads) != len(find_images(content)):
        raise ValueError("upload count does not match embedded image count")
    pieces: list[str] = []
    cursor = 0
    previous_end = -1
    for image, url in uploads:
        if image.start < previous_end or image.start < 0 or image.end < image.start:
            raise ValueError("embedded image positions overlap")
        if image.data_uri != content[image.start:image.end]:
            raise ValueError("embedded image positions changed during upload")
        if not isinstance(url, str) or not url:
            raise ValueError("upload returned an empty asset URL")
        pieces.append(content[cursor:image.start])
        pieces.append(url)
        cursor = image.end
        previous_end = image.end
    pieces.append(content[cursor:])
    return "".join(pieces)


def asset_request(image: EmbeddedImage, *, file_name: str,
                  operation_id: str) -> dict:
    if not operation_id:
        raise ValueError("upload operation_id is required")
    return {
        "content_type": image.mime,
        "data_base64": image.encoded,
        "file_name": file_name,
        "operation_id": operation_id,
    }
