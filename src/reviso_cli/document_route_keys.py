"""User-facing document URL key helpers."""
from __future__ import annotations

import re

_BARE_KEY_RE = re.compile(r"^[0-9a-f]{12}$")
_DOCUMENT_ID_RE = re.compile(r"^doc_[0-9a-f]{12}$")


def public_document_key(document_id: str) -> str:
    value = str(document_id or "").strip()
    if _DOCUMENT_ID_RE.match(value):
        return value.removeprefix("doc_")
    return value


def public_document_path(document_id: str) -> str:
    return f"/documents/{public_document_key(document_id)}"


def document_route_id(route_key: str) -> str:
    """Map a `/documents/<key>` segment onto the one document id.

    Historically this returned a *list* of candidates, because a bare 12-hex
    could have been either `doc_<hex>` or an unrelated `rev_<hex>`, and the
    route layer had to try both. Migration 0068 collapsed `review_id` onto
    `documents.id`, so there is exactly one id and exactly one candidate; a
    `rev_` segment is now just an unknown key.
    """
    value = str(route_key or "").strip()
    if _DOCUMENT_ID_RE.match(value):
        return value
    if _BARE_KEY_RE.match(value):
        return f"doc_{value}"
    raise ValueError("invalid document key")
