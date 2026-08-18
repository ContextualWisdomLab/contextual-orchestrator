"""Resilient orchestration entrypoint for provider-neutral passthrough requests."""

from __future__ import annotations

from typing import Any

from .orchestrator import TaskOrchestrator as BaseTaskOrchestrator
from .orchestrator import _coerce_input_text


class TaskOrchestrator(BaseTaskOrchestrator):
    """Add cross-agent failover to full-shape OpenAI passthrough requests."""

    def proxy_completion(
        self, body: dict[str, Any], *, endpoint: str = "chat/completions"
    ) -> dict[str, Any]:
        """Preserve provider response shape while failing over across ranked agents."""
        messages = body.get("messages")
        if isinstance(messages, list):
            text = self._latest_user_text(messages)
        else:
            text = _coerce_input_text(body.get("input"))
        primary = self._select_agent(text, "worker")
        upstream = {
            key: value
            for key, value in body.items()
            if key not in self._ORCHESTRATION_ONLY_KEYS
        }
        candidates = self._failover_candidates(primary, text, "worker")
        last_error: Exception | None = None
        for agent in candidates:
            candidate_request = dict(upstream)
            candidate_request["model"] = agent.model
            candidate_request["stream"] = False
            try:
                response = self.client.proxy_send(agent, endpoint, candidate_request)
            except Exception as exc:  # noqa: BLE001 - one provider failure routes to the next
                last_error = exc
                self._record_failure(agent.id)
                continue
            self._record_success(agent.id)
            return response
        raise RuntimeError(
            f"all {len(candidates)} candidate agents failed for passthrough endpoint={endpoint}"
        ) from last_error
