"""Bounded cross-provider failover for OpenAI-compatible passthrough requests.

Tool calls, structured responses, and the Responses API must preserve one
provider's raw response shape per attempt. This module keeps that invariant
while advancing to another capability-ranked agent after a failed attempt.
"""

from __future__ import annotations

import time
from typing import Any

from .orchestrator import (
    ModelAgent,
    ModelClient,
    TaskOrchestrator as BaseTaskOrchestrator,
    _coerce_input_text,
    is_transient_error,
)


def _proxy_send_once(
    client: Any,
    agent: ModelAgent,
    endpoint: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Send one raw passthrough request without same-agent transient retries.

    ``ModelClient.proxy_send`` deliberately retries transient failures for
    ordinary callers. Structured Strix requests can be very large, so repeating
    the same saturated model amplifies 429 pressure and consumes the bounded CI
    window. Cross-agent failover therefore owns retries for this path.
    """
    one_shot = getattr(client, "proxy_send_once", None)
    if callable(one_shot):
        return one_shot(agent, endpoint, payload)
    if isinstance(client, ModelClient):
        if agent.base_url.startswith("mock://"):  # pragma: no branch - live egress excluded
            return client._mock_raw(agent, endpoint, payload)
        client._validate_provider(agent)  # pragma: no cover - real provider egress
        return client._send_raw(agent, endpoint, payload)  # pragma: no cover - real provider egress
    return client.proxy_send(agent, endpoint, payload)


class ResilientTaskOrchestrator(BaseTaskOrchestrator):
    """Task orchestrator with one-attempt-per-candidate raw passthrough failover."""

    def proxy_completion(
        self,
        body: dict[str, Any],
        *,
        endpoint: str = "chat/completions",
    ) -> dict[str, Any]:
        """Preserve raw OpenAI shapes while failing over across ranked agents.

        Each candidate receives exactly one upstream attempt. A transient
        failure opens that candidate's circuit immediately for the cooldown
        window, preventing the next request from repeating an expensive 429.
        Provider-specific ``tools``, ``tool_choice``, and ``response_format``
        fields are copied unchanged to every candidate.
        """
        messages = body.get("messages")
        if isinstance(messages, list):
            text = self._latest_user_text(messages)
        else:
            text = _coerce_input_text(body.get("input"))

        primary = self._select_agent(text, "worker")
        candidates = self._failover_candidates(primary, text, "worker")
        upstream_template = {
            key: value
            for key, value in body.items()
            if key not in self._ORCHESTRATION_ONLY_KEYS
        }
        upstream_template["stream"] = False

        last_error: Exception | None = None
        for agent in candidates:
            upstream = dict(upstream_template)
            upstream["model"] = agent.model
            try:
                result = _proxy_send_once(self.client, agent, endpoint, upstream)
            except Exception as exc:  # noqa: BLE001 - failed candidate yields to the next
                last_error = exc
                self._record_failure(agent.id)
                if is_transient_error(exc):
                    state = self._circuit[agent.id]
                    state["failures"] = max(
                        state["failures"],
                        float(self.circuit_failure_threshold),
                    )
                    state["opened_at"] = time.monotonic()
                continue
            self._record_success(agent.id)
            return result

        raise RuntimeError(
            f"all {len(candidates)} candidate agents failed for passthrough endpoint={endpoint}"
        ) from last_error
