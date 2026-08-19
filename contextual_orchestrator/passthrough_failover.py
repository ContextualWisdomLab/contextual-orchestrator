"""Bounded cross-provider failover for OpenAI-compatible passthrough requests.

Tool calls, structured responses, and Responses API calls must preserve one
provider's raw response shape. This module keeps that contract while advancing
to another capability-ranked model when the caller selected the virtual
``contextual-orchestrator`` model and an upstream candidate fails.
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
    """Send one raw passthrough attempt without same-model transient retries."""
    one_shot = getattr(client, "proxy_send_once", None)
    if callable(one_shot):
        return one_shot(agent, endpoint, payload)
    if isinstance(client, ModelClient):
        if agent.base_url.startswith("mock://"):
            return client._mock_raw(agent, endpoint, payload)
        destination = client._validate_provider(agent)  # pragma: no cover - live egress
        return client._send_raw(agent, endpoint, payload, destination)  # pragma: no cover - live egress
    return client.proxy_send(agent, endpoint, payload)


class TaskOrchestrator(BaseTaskOrchestrator):
    """Add bounded provider failover to full-shape OpenAI passthrough requests."""

    def proxy_completion(
        self,
        body: dict[str, Any],
        *,
        endpoint: str = "chat/completions",
    ) -> dict[str, Any]:
        """Preserve raw response shapes while failing over virtual-model requests.

        An explicitly requested concrete model remains sticky: serving another
        model would violate the caller's model contract. Requests for the virtual
        ``contextual-orchestrator`` model, or requests that omit ``model``, may
        advance through capability-ranked candidates. Every candidate receives
        at most one passthrough attempt, so a 429 is never amplified by replaying
        the same large tool request.
        """
        messages = body.get("messages")
        if isinstance(messages, list):
            text = self._latest_user_text(messages)
        else:
            text = _coerce_input_text(body.get("input"))

        requested_model = body.get("model")
        requested_agent = self._requested_agent(requested_model)
        if requested_agent is not None:
            if requested_agent.disabled:
                raise RuntimeError(f"requested model {requested_model!r} is disabled")
            candidates = [requested_agent]
        else:
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
            except Exception as exc:  # noqa: BLE001 - a failed virtual candidate yields to the next
                last_error = exc
                self._record_failure(agent.id)
                if is_transient_error(exc):
                    with self._circuit_lock:
                        state = self._circuit.setdefault(
                            agent.id,
                            {"failures": 0.0, "opened_at": 0.0},
                        )
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
