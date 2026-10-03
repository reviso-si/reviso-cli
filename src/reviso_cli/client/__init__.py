"""HTTP client for Reviso server — CLI's only path to server state."""
from __future__ import annotations

from urllib.parse import urlencode

from .collab import CollabClientMixin
from .http import request_json
from .participation import ParticipationClientMixin


class RevisoClient(CollabClientMixin, ParticipationClientMixin):
    def __init__(self, server_url: str,
                 owner_api_key: str | None = None):
        self.url = server_url.rstrip("/")
        self._key = owner_api_key

    def _request(self, method: str, path: str, *,
                 body: dict | None = None,
                 guest_id: str | None = None,
                 guest_token: str | None = None) -> dict:
        return request_json(
            self.url, self._key, method, path, body=body, guest_id=guest_id,
            guest_token=guest_token, source="python_client")

    def health(self) -> dict:
        return self._request("GET", "/healthz")
    def ready(self) -> dict:
        return self._request("GET", "/readyz")
    def version_info(self) -> dict:
        return self._request("GET", "/version")
    def publish(self, title: str, content: str,
                source_format: str = "markdown",
                description: str = "Initial draft",
                workspace_id: str = "",
                parent_id: str = "",
                operation_id: str | None = None,
                background: list[dict] | None = None,
                document_kind: str | None = None,
                deck_contract_version: str | None = None) -> dict:
        # operation_id (P1c exactly-once) is NOT minted here: the client cannot
        # tell a fresh command from a transport retry. The command owner (CLI /
        # MCP) generates it once and reuses it across the retries of ONE publish.
        body = {"title": title, "content": content,
                "source_format": source_format,
                "description": description,
                "workspace_id": workspace_id,
                "parent_id": parent_id}
        if operation_id is not None:
            body["operation_id"] = operation_id
        if background is not None:
            body["background"] = background
        if document_kind is not None:
            body["document_kind"] = document_kind
        if deck_contract_version is not None:
            body["deck_contract_version"] = deck_contract_version
        return self._request("POST", "/api/documents", body=body)
    def update(self, review_id: str, content: str, base_version_id: str,
               description: str, source_format: str | None = None,
               agent_name: str = "Agent",
               operation_id: str | None = None,
               background: list[dict] | None = None,
               document_kind: str | None = None,
               deck_contract_version: str | None = None) -> dict:
        body = {"content": content, "base_version_id": base_version_id,
                "description": description, "source_format": source_format,
                "agent_name": agent_name}
        if operation_id is not None:
            body["operation_id"] = operation_id
        if background is not None:
            body["background"] = background
        if document_kind is not None:
            body["document_kind"] = document_kind
        if deck_contract_version is not None:
            body["deck_contract_version"] = deck_contract_version
        return self._request("POST", f"/api/documents/{review_id}/agent-update", body=body)
    def patch_sections(self, review_id: str, ops: list[dict],
                       base_version_id: str, base_content_hash: str,
                       description: str, source_format: str | None = None,
                       agent_name: str = "Agent") -> dict:
        body = {"ops": ops, "base_version_id": base_version_id,
                "base_content_hash": base_content_hash,
                "description": description, "source_format": source_format,
                "agent_name": agent_name}
        return self._request("POST", f"/api/documents/{review_id}/agent-update", body=body)
    def patch_blocks(self, review_id: str, ops: list[dict],
                     base_version_id: str, base_content_hash: str,
                     description: str, source_format: str | None = None,
                     agent_name: str = "Agent") -> dict:
        return self.apply_patch(
            review_id, ops, base_version_id, description,
            source_format=source_format, agent_name=agent_name)
    def apply_patch(self, review_id: str, ops: list[dict],
                    base_version_id: str, description: str,
                    base_update_seq: int | None = None,
                    idempotency_key: str | None = None,
                    schema_version: int | None = None,
                    source_format: str | None = None,
                    agent_name: str = "Agent",
                    run_id: str | None = None,
                    attempt: int | None = None,
                    note: str | None = None) -> dict:
        body: dict = {"ops": ops, "base_version_id": base_version_id,
                      "description": description, "source_format": source_format,
                      "agent_name": agent_name}
        for key, value in (("base_update_seq", base_update_seq),
                           ("idempotency_key", idempotency_key),
                           ("schema_version", schema_version),
                           ("run_id", run_id), ("attempt", attempt),
                           ("note", note)):
            if value is not None:
                body[key] = value
        return self._request(
            "POST", f"/api/documents/{review_id}/apply-patch", body=body)
    def edit(self, review_id: str, content: str, base_version_id: str,
             description: str, source_format: str | None = None,
             base_content_hash: str = "") -> dict:
        # The server requires a guard against the current head. When the caller
        # omits it, read the current hash first so the edit lands on top of any
        # unsaved change instead of orphaning it.
        if not base_content_hash:
            base_content_hash = str(
                self.latest_content(review_id).get("content_hash", ""))
        return self._request("POST", f"/api/documents/{review_id}/edit",
                             body={"content": content, "base_version_id": base_version_id,
                                   "description": description,
                                   "source_format": source_format,
                                   "base_content_hash": base_content_hash})
    def rollback(self, review_id: str, target_version_id: str,
                 base_version_id: str, description: str) -> dict:
        return self._request("POST", f"/api/documents/{review_id}/rollback",
                             body={"target_version_id": target_version_id, "base_version_id": base_version_id,
                                   "description": description})
    def status(self, review_id: str) -> dict:
        return self._request("GET", f"/api/documents/{review_id}/status")
    def rename(self, review_id: str, title: str) -> dict:
        return self._request("POST", f"/api/documents/{review_id}/rename",
                             body={"title": title})
    def packet(self, review_id: str,
               thread_ids: list[str] | None = None,
               version: str = "1") -> dict:
        path = f"/api/documents/{review_id}/agent-packet"
        params = []
        if version != "1":
            params.append(f"v={version}")
        if thread_ids: params.extend(f"thread_id={tid}" for tid in thread_ids)
        if params:
            path = f"{path}?{'&'.join(params)}"
        return self._request("GET", path)
    def versions(self, review_id: str) -> dict:
        return self._request("GET", f"/api/documents/{review_id}/versions")
    def timeline(self, review_id: str, limit: int = 200,
                 offset: int = 0) -> dict:
        path = f"/api/documents/{review_id}/timeline?limit={limit}&offset={offset}"
        return self._request("GET", path)
    def diff(self, review_id: str, from_version_id: str,
             to_version_id: str) -> dict:
        path = f"/api/documents/{review_id}/diff?from={from_version_id}&to={to_version_id}"
        return self._request("GET", path)
    def version_content(self, review_id: str, version_id: str) -> dict:
        return self._request("GET",
            f"/api/documents/{review_id}/versions/{version_id}/content")
    def latest_content(self, review_id: str) -> dict:
        return self._request("GET", f"/api/documents/{review_id}/latest-content")
    def sections(self, review_id: str) -> dict:
        return self._request("GET", f"/api/documents/{review_id}/sections")
    def blocks(self, review_id: str) -> dict:
        return self._request("GET", f"/api/documents/{review_id}/blocks")
    def sync_status(self, review_id: str) -> dict:
        return self._request("GET", f"/api/documents/{review_id}/sync")
    def dashboard(self, workspace_id: str = "", limit: int = 0,
                  offset: int = 0, archived: bool = False) -> dict:
        # limit/offset/archived were reachable on the route (web_routes_read.py)
        # and on the store, but not through this client -- so an agent could
        # never page past the server default nor see the recycle bin.
        query = {}
        if workspace_id:
            query["workspace_id"] = workspace_id
        if limit:
            query["limit"] = str(limit)
        if offset:
            query["offset"] = str(offset)
        if archived:
            query["archived"] = "1"
        path = "/api/dashboard/documents"
        if query:
            path += "?" + urlencode(query)
        return self._request("GET", path)
    def workspaces(self) -> dict:
        return self._request("GET", "/api/workspaces")
    def favorites(self) -> dict:
        return self._request("GET", "/api/favorites")
    def favorite(self, review_id: str) -> dict:
        return self._request("POST", "/api/favorites",
                             body={"document_id": review_id})
    def unfavorite(self, review_id: str) -> dict:
        return self._request("POST", "/api/favorites/remove",
                             body={"document_id": review_id})
    def export_review(self, review_id: str) -> dict:
        return self._request("GET", f"/api/documents/{review_id}/export")
    def import_review(self, bundle: dict, workspace_id: str = "",
                      parent_id: str = "") -> dict:
        body = dict(bundle)
        if workspace_id:
            body["workspace_id"] = workspace_id
        if parent_id:
            body["parent_id"] = parent_id
        return self._request("POST", "/api/documents/import", body=body)
    def archive(self, review_id: str) -> dict:
        return self._request("POST", f"/api/documents/{review_id}/archive",
                             body={})

    def restore(self, review_id: str) -> dict:
        return self._request("POST", f"/api/documents/{review_id}/restore",
                             body={})

    def workflow(self, review_id: str) -> dict:
        return self._request("GET", f"/api/documents/{review_id}/workflow")

    def members(self, workspace_id: str) -> dict:
        return self._request(
            "GET", f"/api/workspace/members?workspace_id={workspace_id}")

    def create_member(self, email: str, display_name: str,
                      role: str = "collaborator",
                      workspace_id: str = "") -> dict:
        body = {"email": email, "display_name": display_name,
                "role": role, "workspace_id": workspace_id}
        return self._request("POST", "/api/workspace/members", body=body)

    def participants(self, review_id: str) -> dict:
        return self._request("GET", f"/api/documents/{review_id}/participants")
