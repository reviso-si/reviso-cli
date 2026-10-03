"""Recovery + experience-layer client methods.

Mixed into ``RevisoClient``; relies on the host class providing ``_request``.
Split out to keep ``client.py`` under the repo's per-file line limit — these are
the newer failed-intent recovery and presence-heartbeat surfaces, cohesive
enough to live together and away from the core content/version calls.
"""
from __future__ import annotations


class CollabClientMixin:
    def list_failed_intents(self, review_id: str) -> dict:
        return self._request("GET", f"/api/documents/{review_id}/failed-intents")

    def get_failed_intent(self, review_id: str, intent_id: str) -> dict:
        return self._request(
            "GET", f"/api/documents/{review_id}/failed-intents/{intent_id}")

    def resolve_failed_intent(self, review_id: str, intent_id: str,
                              status: str) -> dict:
        return self._request(
            "POST",
            f"/api/documents/{review_id}/failed-intents/{intent_id}/resolve",
            body={"status": status})

    def signal_activity(self, review_id: str, *,
                        activity_state: str | None = None,
                        block_id: str | None = None,
                        done: bool = False) -> dict:
        # Experience-layer presence heartbeat. done (or the 'idle' shorthand)
        # releases the row; otherwise upsert this actor's advisory activity.
        if done or activity_state == "idle":
            return self._request("POST", f"/api/documents/{review_id}/presence",
                                 body={"release": True})
        body: dict = {"activity_state": activity_state}
        if block_id:
            body["block_id"] = block_id
        return self._request("POST", f"/api/documents/{review_id}/presence",
                             body=body)
