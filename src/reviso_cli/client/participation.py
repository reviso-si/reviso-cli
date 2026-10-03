"""Webhook, invite, event-wait, and comment client methods.

Split out of client.py as a mixin so RevisoClient stays under the 300-line
source limit. These methods reach the server exclusively through
self._request / self.url / self._key, which the composed RevisoClient
supplies."""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from .errors import raise_for_status


class ParticipationClientMixin:
    def create_webhook(self, review_id: str, url: str,
                       events: list[str]) -> dict:
        result = self._request("POST", f"/api/documents/{review_id}/webhooks",
                               body={"url": url, "events": events})
        print("\u26a0 Save this secret now \u2014 it won\u2019t be shown again")
        return result

    def list_webhooks(self, review_id: str) -> dict:
        return self._request("GET", f"/api/documents/{review_id}/webhooks")

    def delete_webhook(self, webhook_id: str) -> dict:
        return self._request("POST", f"/api/webhooks/{webhook_id}/delete",
                             body={})

    def retry_webhook_delivery(self, delivery_id: str) -> dict:
        return self._request("POST", f"/api/webhook-deliveries/{delivery_id}/retry", body={})

    def create_invite(self, review_id: str, email: str,
                      access: str = "comment") -> dict:
        body = {"email": email, "access": access}
        return self._request("POST", f"/api/documents/{review_id}/invites",
                             body=body)

    def list_invites(self, review_id: str) -> dict:
        return self._request("GET", f"/api/documents/{review_id}/invites")

    def revoke_invite(self, invite_id: str) -> dict:
        return self._request("POST", f"/api/invites/{invite_id}/revoke",
                             body={})

    def accept_invite(self, invite_id: str, token: str) -> dict:
        return self._request("POST", f"/api/invites/{invite_id}/accept",
                             body={"token": token})

    def wait_for_events(self, review_id: str, after_seq: int = 0,
                        timeout: int = 30) -> dict:
        t = min(timeout, 60)
        path = (f"/api/documents/{review_id}/events"
                f"?after={after_seq}&timeout={t}")
        url = f"{self.url}{path}"
        hdrs = {}
        if self._key:
            hdrs["Authorization"] = f"Bearer {self._key}"
        req = urllib.request.Request(url, headers=hdrs, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=t + 10) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            # Second instance of the truncation bug fixed in client_http:
            # raise_for_status must see the WHOLE body, or a long server
            # envelope gets sliced mid-JSON and a classified 400 reaches the
            # agent as INTERNAL_ERROR. The 300-char cap lives in
            # raise_for_status, on the unstructured fallback only.
            raise_for_status(e.code, e.read().decode("utf-8", errors="replace"))
        except urllib.error.URLError as e:
            raise SystemExit(f"connection error: {e.reason}") from e

    def agent_comment(self, review_id: str, agent_name: str,
                      severity: str, body: str,
                      anchor: dict | None = None,
                      mentions: list[str] | None = None) -> dict:
        payload: dict = {"agent_name": agent_name,
                         "severity": severity, "body": body,
                         "anchor": anchor or {}}
        if mentions is not None:
            payload["mentions"] = mentions
        return self._request("POST",
                             f"/api/documents/{review_id}/agent-comments",
                             body=payload)

    def agent_comments_batch(self, review_id: str, agent_name: str,
                             comments: list) -> dict:
        """Many comments, one round trip. Always inspect `results`: the
        response is 200 even when individual entries failed."""
        return self._request(
            "POST", f"/api/documents/{review_id}/agent-comments/batch",
            body={"agent_name": agent_name, "comments": comments})

    def guest(self, review_id: str, display_name: str,
              email: str | None = None) -> dict:
        return self._request("POST", f"/api/documents/{review_id}/guest",
                             body={"display_name": display_name,
                                   "email": email})

    def comment(self, review_id: str, guest_id: str, guest_token: str,
                body: str, anchor: dict) -> dict:
        return self._request("POST", f"/api/documents/{review_id}/comments",
                             body={"body": body, "anchor": anchor},
                             guest_id=guest_id, guest_token=guest_token)

    def reply(self, thread_id: str, guest_id: str, guest_token: str,
              body: str) -> dict:
        return self._request("POST", f"/api/threads/{thread_id}/replies",
                             body={"body": body},
                             guest_id=guest_id, guest_token=guest_token)

    def resolve(self, thread_id: str, guest_id: str, guest_token: str,
                reason: str) -> dict:
        return self._request("POST", f"/api/threads/{thread_id}/resolve",
                             body={"reason": reason},
                             guest_id=guest_id, guest_token=guest_token)

    def threads(self, review_id: str) -> dict:
        return self._request("GET", f"/api/documents/{review_id}/threads")
