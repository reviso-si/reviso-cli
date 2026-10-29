"""Deterministic data-URI extraction and rewrite for HTML decks.

The server intentionally keeps a bounded inline-data budget. This module makes
the recoverable path explicit: upload each embedded image, then replace only the
exact URI in the deck. It has no HTTP or CLI dependencies so DSH and MCP can
share the same rules.
"""

from __future__ import annotations

import base64
import binascii
import re
from dataclasses import dataclass

_IMG_TAG = re.compile(r"<img\b[^>]*>", re.IGNORECASE | re.DOTALL)
_SRC_ATTR = re.compile(
    r"""\bsrc\s*=\s*(?:"(?P<double>[^"]*)"|'(?P<single>[^']*)'|(?P<bare>[^\s>]+))""",
    re.IGNORECASE | re.DOTALL,
)
_DATA_URI = re.compile(
    r"""data:(image/(?:png|jpeg|gif|webp));base64,([^\s"']*)""",
    re.IGNORECASE,
)
_ASSET_URL = re.compile(r"/api/documents/[^/\s]+/assets/[^/\s]+\Z")
_ALLOWED = {"image/png", "image/jpeg", "image/gif", "image/webp"}
_MAX_DECODED = 5 * 1024 * 1024


@dataclass(frozen=True)
class EmbeddedImage:
    mime: str
    encoded: str
    decoded: bytes
    start: int
    end: int
    raw_uri: str

    @property
    def data_uri(self) -> str:
        return self.raw_uri


def _decode_image(match: re.Match[str], *, position: int) -> EmbeddedImage:
    mime = match.group(1).lower()
    encoded = match.group(2)
    try:
        decoded = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError(
            f"embedded {mime} at byte {position} is not valid base64") from exc
    if not decoded:
        raise ValueError(f"embedded {mime} at byte {position} is empty")
    if len(decoded) > _MAX_DECODED:
        raise ValueError(
            f"embedded {mime} at byte {position} is {len(decoded)} bytes; "
            f"maximum upload image size is {_MAX_DECODED} bytes")
    return EmbeddedImage(
        mime=mime, encoded=encoded, decoded=decoded,
        start=position, end=position + len(match.group(0)),
        raw_uri=match.group(0),
    )


def find_images(content: str) -> list[EmbeddedImage]:
    """Return supported image data URIs from <img src> in source order.

    Unsupported schemes (for example SVG) remain untouched for the deck contract
    validator. Supported raster images that cannot be decoded or exceed the
    upload budget fail immediately with an actionable error instead of being
    silently left for a later, less precise failure.
    """
    if not isinstance(content, str):
        raise TypeError("deck content must be a string")
    found: list[EmbeddedImage] = []
    for tag in _IMG_TAG.finditer(content):
        src = _SRC_ATTR.search(tag.group(0))
        if src is None:
            continue
        group_name = "double" if src.group("double") is not None else (
            "single" if src.group("single") is not None else "bare")
        value = src.group(group_name)
        data = _DATA_URI.fullmatch(value)
        if data is None:
            continue
        found.append(_decode_image(
            data, position=tag.start() + src.start(group_name)))
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
        if image.raw_uri != content[image.start:image.end]:
            raise ValueError("embedded image positions changed during upload")
        if not isinstance(url, str) or not _ASSET_URL.fullmatch(url):
            raise ValueError("upload returned an invalid asset URL")
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
