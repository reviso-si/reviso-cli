"""Shared document search for CLI and MCP."""
from __future__ import annotations

from .errors import ValidationError

SEARCH_FIELDS = (
    "title", "document_id", "creator_name",
    "lifecycle_status", "last_event_type", "workspace_id",
)


def search_documents(client, query: str, *, workspace_id: str = "",
                     limit: int = 10, archived: bool = False,
                     include_content: bool = False) -> dict:
    term = _term(query)
    max_results = _limit(limit)
    reviews = client.dashboard(
        workspace_id=workspace_id, limit=100, offset=0, archived=archived
    ).get("reviews", [])
    matches = []
    for row in reviews:
        match = _metadata_match(row, term)
        if match is None and include_content:
            match = _content_match(client, row, term)
        if match is not None:
            matches.append({**_summary(row), **match})
        if len(matches) >= max_results:
            break
    return {
        "query": query,
        "matches": matches,
        "scanned": len(reviews),
        "include_content": include_content,
    }


def _term(value: str) -> str:
    term = str(value or "").strip().lower()
    if not term:
        raise ValidationError("query is required")
    return term


def _limit(value: int) -> int:
    return max(1, min(int(value or 10), 50))


def _metadata_match(row: dict, term: str) -> dict | None:
    for field in SEARCH_FIELDS:
        text = str(row.get(field) or "")
        if term in text.lower():
            return {"match_field": field, "snippet": _snippet(text, term)}
    return None


def _content_match(client, row: dict, term: str) -> dict | None:
    content = str(client.latest_content(row["document_id"]).get("content") or "")
    if term not in content.lower():
        return None
    return {"match_field": "content", "snippet": _snippet(content, term)}


def _summary(row: dict) -> dict:
    keys = (
        "document_id", "workspace_id", "title",
        "lifecycle_status", "current_version_id",
        "updated_at", "created_at", "thread_count", "unresolved_count",
        "last_event_type", "last_event_at",
    )
    return {key: row.get(key) for key in keys if key in row}


def _snippet(text: str, term: str, radius: int = 56) -> str:
    lower = text.lower()
    index = lower.find(term)
    if index < 0:
        return text[: radius * 2].strip()
    start = max(0, index - radius)
    end = min(len(text), index + len(term) + radius)
    prefix = "..." if start else ""
    suffix = "..." if end < len(text) else ""
    return f"{prefix}{text[start:end].strip()}{suffix}"
