"""Verbose/DEBUG-level operational logging for routing, failover, and discovery.

Every event asserted here already existed as a secret-free structured value
(an audit event, a classified error, a plain agent id) before this feature —
the gap this closes is that none of it was ever visible in live process
output, which is exactly the evidence a request-time incident like an
``orchestrator/free`` pool exhaustion needs to root-cause. These tests prove
both halves: the evidence becomes visible at DEBUG/INFO/WARNING, and nothing
secret-shaped ever reaches ``caplog.text``.
"""

from __future__ import annotations

import json
import logging
import sys
import urllib.error
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.credentials import register_credential  # noqa: E402
from contextual_orchestrator.model_discovery import (  # noqa: E402
    ProviderModelSource,
    discover_provider_models,
)
from contextual_orchestrator.orchestrator import ModelClient  # noqa: E402
from contextual_orchestrator.provider_errors import classify_provider_failure  # noqa: E402


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://provider.example/chat/completions", code, "err", None, None)


def _free_pool_orchestrator(
    client: ModelClient, *, free_ids: tuple[str, ...], priced_id: str = "priced_worker"
) -> TaskOrchestrator:
    agents = [
        ModelAgent(free_id, f"{free_id}-model", tags=("reasoning", "cost:free"))
        for free_id in free_ids
    ] + [
        ModelAgent(priced_id, "priced-model", tags=("reasoning",), priority=99),
    ]
    orchestrator = TaskOrchestrator(
        agents, client=client, tool_retry_attempts=1, tool_retry_backoff_seconds=0.0
    )
    orchestrator._triage_fn = lambda text: False
    orchestrator.policy = replace(orchestrator.policy, realtime_judge=False)
    return orchestrator


def test_audit_event_emits_debug_log_with_event_type_and_stream(caplog) -> None:
    """`_append_audit_event` surfaces the same event through `logging` at DEBUG."""
    orchestrator = _free_pool_orchestrator(ModelClient(), free_ids=("free_route_a",))
    with caplog.at_level(logging.DEBUG, logger="contextual_orchestrator.orchestrator"):
        orchestrator._append_audit_event("workflow_run_created", {"mode": "route"})
    assert "orchestrator.audit_event" in caplog.text
    assert "event_type=workflow_run_created" in caplog.text
    assert "stream=audit" in caplog.text


def test_audit_event_log_redacts_secret_shaped_detail_values(caplog) -> None:
    """A stray credential-shaped string in an audit detail never reaches the log."""
    orchestrator = _free_pool_orchestrator(ModelClient(), free_ids=("free_route_a",))
    with caplog.at_level(logging.DEBUG, logger="contextual_orchestrator.orchestrator"):
        orchestrator._append_audit_event(
            "workflow_run_created",
            {"mode": "route", "note": "api_key: sk-super-secret-value-123456"},
        )
    assert "[REDACTED]" in caplog.text
    assert "sk-super-secret-value-123456" not in caplog.text


def test_audit_event_no_log_below_debug_threshold(caplog) -> None:
    """No log line is emitted when the logger's effective level excludes DEBUG."""
    orchestrator = _free_pool_orchestrator(ModelClient(), free_ids=("free_route_a",))
    with caplog.at_level(logging.WARNING, logger="contextual_orchestrator.orchestrator"):
        orchestrator._append_audit_event("workflow_run_created", {"mode": "route"})
    assert "orchestrator.audit_event" not in caplog.text
    # The durable/in-memory audit trail is unaffected by the logging threshold.
    assert orchestrator._audit_events[-1]["event_type"] == "workflow_run_created"


def test_failover_candidates_resolved_audit_event_reports_funnel_counts() -> None:
    """The candidate-resolution funnel records why the pool is the size it is."""
    orchestrator = _free_pool_orchestrator(
        ModelClient(), free_ids=("free_route_a", "free_route_b")
    )
    primary = orchestrator._agent("free_route_a")
    orchestrator._failover_candidates(
        primary, "task text", "worker", allowed_agent_ids={"free_route_a", "free_route_b"}
    )
    events = [e for e in orchestrator._audit_events if e["event_type"] == "failover_candidates_resolved"]
    assert events, "expected a failover_candidates_resolved audit event"
    detail = events[-1]["event_detail"]
    assert detail["role"] == "worker"
    assert detail["primary_agent_id"] == "free_route_a"
    assert detail["ranked_count"] == 2
    assert detail["excluded_disabled"] == 0
    assert detail["excluded_zdr"] == 0
    assert detail["healthy_count"] == detail["ranked_count"]
    assert not detail["used_circuit_open_fallback"]
    assert set(detail["resolved_agent_ids"]) == {"free_route_a", "free_route_b"}


def test_failover_candidates_resolved_reports_circuit_open_fallback() -> None:
    """When every eligible candidate is circuit-open, the funnel says so explicitly."""
    orchestrator = _free_pool_orchestrator(ModelClient(), free_ids=("free_route_a", "free_route_b"))
    for agent_id in ("free_route_a", "free_route_b"):
        for _ in range(orchestrator.circuit_failure_threshold):
            orchestrator._record_failure(agent_id)
    primary = orchestrator._agent("free_route_a")
    # Scope to the free pool explicitly, matching how the real orchestrator/free
    # request path restricts failover -- without this, the lower-level
    # _failover_candidates primitive has no free/priced boundary of its own
    # (that boundary is enforced by the caller via allowed_agent_ids).
    resolved = orchestrator._failover_candidates(
        primary, "task text", "worker", allowed_agent_ids={"free_route_a", "free_route_b"}
    )
    assert [agent.id for agent in resolved]
    events = [e for e in orchestrator._audit_events if e["event_type"] == "failover_candidates_resolved"]
    detail = events[-1]["event_detail"]
    assert detail["healthy_count"] == 0
    assert detail["used_circuit_open_fallback"] is True


def test_candidate_pool_exhausted_audit_event_on_full_failure() -> None:
    """Exhausting every candidate records which ones were tried and the final error kind."""
    calls: list[str] = []

    class AlwaysFails(ModelClient):
        def chat(self, agent: ModelAgent, messages: list, temperature: float = 0.2) -> str:  # type: ignore[override]
            calls.append(agent.id)
            raise classify_provider_failure(_http_error(500), agent_id=agent.id, model=agent.model)

    orchestrator = _free_pool_orchestrator(
        AlwaysFails(), free_ids=("free_route_a", "free_route_b")
    )
    with pytest.raises(Exception):
        orchestrator.route_once(
            [{"role": "user", "content": "route this"}],
            model_name=TaskOrchestrator.FREE_MODEL,
        )
    events = [e for e in orchestrator._audit_events if e["event_type"] == "candidate_pool_exhausted"]
    assert events, "expected a candidate_pool_exhausted audit event"
    detail = events[-1]["event_detail"]
    assert detail["role"] == "worker"
    assert set(detail["candidate_agent_ids"]) == {"free_route_a", "free_route_b"}
    assert detail["candidate_count"] == 2
    assert detail["final_error_kind"] != "unknown"


def test_circuit_breaker_open_and_close_transitions_are_logged(caplog) -> None:
    """Circuit-breaker state transitions are visible at WARNING/INFO, by agent id only."""
    orchestrator = _free_pool_orchestrator(ModelClient(), free_ids=("free_route_a",))
    with caplog.at_level(logging.INFO, logger="contextual_orchestrator.orchestrator"):
        for _ in range(orchestrator.circuit_failure_threshold - 1):
            orchestrator._record_failure("free_route_a")
        assert "circuit_breaker_opened" not in caplog.text
        orchestrator._record_failure("free_route_a")
        assert "circuit_breaker_opened agent_id=free_route_a" in caplog.text
        caplog.clear()
        orchestrator._record_success("free_route_a")
        assert "circuit_breaker_closed agent_id=free_route_a reason=success" in caplog.text


def test_circuit_breaker_success_on_healthy_agent_does_not_log(caplog) -> None:
    """A success on an agent with no open-circuit state logs nothing (no noise)."""
    orchestrator = _free_pool_orchestrator(ModelClient(), free_ids=("free_route_a",))
    with caplog.at_level(logging.INFO, logger="contextual_orchestrator.orchestrator"):
        orchestrator._record_success("free_route_a")
    assert "circuit_breaker_closed" not in caplog.text


class _DiscoveryResponse:
    def __init__(self, payload: dict) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return self._body


def test_discover_provider_models_skip_logs_provider_and_credential_name_only(caplog) -> None:
    """A missing credential is logged by name, never left silently unexplained."""
    source = ProviderModelSource(
        provider_name="test_provider_alpha",
        credential_name="TEST_PROVIDER_ALPHA_API_KEY",
        list_url="https://alpha.example/v1/models",
        chat_base_url="https://alpha.example/v1",
    )
    with caplog.at_level(logging.INFO, logger="contextual_orchestrator.model_discovery"):
        assert discover_provider_models(source) == []
    assert "provider_discovery_skipped provider=test_provider_alpha" in caplog.text
    assert "credential_name=TEST_PROVIDER_ALPHA_API_KEY" in caplog.text
    assert "reason=no_credential_registered" in caplog.text


def test_discover_provider_models_success_logs_discovered_and_free_counts(caplog) -> None:
    """A successful fetch reports how many models -- and how many free ones -- it found."""
    source = ProviderModelSource(
        provider_name="test_provider_beta",
        credential_name="TEST_PROVIDER_BETA_API_KEY",
        list_url="https://beta.example/v1/models",
        chat_base_url="https://beta.example/v1",
    )
    register_credential("TEST_PROVIDER_BETA_API_KEY", "sk-beta-not-a-real-secret")
    payload = {
        "data": [
            {"id": "beta/model-one", "pricing": {"prompt": "0", "completion": "0"}},
            {"id": "beta/model-two", "pricing": {"prompt": "0.001", "completion": "0.002"}},
        ]
    }
    with patch(
        "contextual_orchestrator.model_discovery.urllib.request.urlopen",
        return_value=_DiscoveryResponse(payload),
    ):
        with caplog.at_level(logging.INFO, logger="contextual_orchestrator.model_discovery"):
            discovered = discover_provider_models(source)
    assert len(discovered) == 2
    assert "provider_discovery_completed provider=test_provider_beta" in caplog.text
    assert "discovered_count=2" in caplog.text
    assert "free_count=1" in caplog.text
    assert "sk-beta-not-a-real-secret" not in caplog.text


def test_discover_provider_models_failure_logs_classified_error_never_raw_body(caplog) -> None:
    """A provider fetch failure logs the classified error code, never the raw exception."""
    source = ProviderModelSource(
        provider_name="test_provider_gamma",
        credential_name="TEST_PROVIDER_GAMMA_API_KEY",
        list_url="https://gamma.example/v1/models",
        chat_base_url="https://gamma.example/v1",
    )
    register_credential("TEST_PROVIDER_GAMMA_API_KEY", "sk-gamma-not-a-real-secret")

    def urlopen(request, timeout=None):
        raise urllib.error.HTTPError(
            "https://gamma.example/v1/models",
            403,
            "Forbidden",
            None,
            None,
        )

    with patch("contextual_orchestrator.model_discovery.urllib.request.urlopen", side_effect=urlopen):
        with caplog.at_level(logging.WARNING, logger="contextual_orchestrator.model_discovery"):
            from contextual_orchestrator.model_discovery import ProviderDiscoveryError

            with pytest.raises(ProviderDiscoveryError):
                discover_provider_models(source)
    assert "provider_discovery_failed provider=test_provider_gamma error_code=http_status_403" in caplog.text
    assert "sk-gamma-not-a-real-secret" not in caplog.text


def test_models_dev_fetch_retries_and_exhaustion_are_logged(caplog) -> None:
    """Each retry, a recovered attempt, and full exhaustion are all visible."""
    from contextual_orchestrator.model_discovery import (
        _MODELS_DEV_FETCH_ATTEMPTS,
        _fetch_models_dev_metadata,
    )

    def always_times_out(url, *, api_key="", auth_scheme="Bearer", timeout):
        raise TimeoutError("simulated models.dev timeout")

    with patch("contextual_orchestrator.model_discovery._fetch_json", side_effect=always_times_out):
        with patch("contextual_orchestrator.model_discovery.time.sleep"):
            with caplog.at_level(logging.WARNING, logger="contextual_orchestrator.model_discovery"):
                result = _fetch_models_dev_metadata(timeout=1.0)
    assert result is None
    assert caplog.text.count("models_dev_fetch_retry") == _MODELS_DEV_FETCH_ATTEMPTS - 1
    assert "models_dev_fetch_exhausted" in caplog.text
    assert "orchestrator_free_coverage_degraded=true" in caplog.text


def test_models_dev_fetch_recovery_after_retry_is_logged(caplog) -> None:
    """Succeeding only after a retry is distinguished from succeeding on the first try."""
    from contextual_orchestrator.model_discovery import _fetch_models_dev_metadata

    attempts = {"count": 0}

    def fails_once_then_succeeds(url, *, api_key="", auth_scheme="Bearer", timeout):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise TimeoutError("simulated transient timeout")
        return {"models": {}}

    with patch(
        "contextual_orchestrator.model_discovery._fetch_json", side_effect=fails_once_then_succeeds
    ):
        with patch("contextual_orchestrator.model_discovery.time.sleep"):
            with caplog.at_level(logging.INFO, logger="contextual_orchestrator.model_discovery"):
                result = _fetch_models_dev_metadata(timeout=1.0)
    assert result == {"models": {}}
    assert "models_dev_fetch_recovered attempt=2" in caplog.text
