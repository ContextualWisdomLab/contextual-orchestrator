"""Rate-limit-aware admission under a 429 storm.

Evidence: org CI review lanes (noema run 34758641142, strix run 34758679736)
saw every `orchestrator/free` candidate return HTTP 429 within ~50ms during a
free-pool rate-limit storm, and the gateway simply failed the request instead
of honoring the provider's declared cooldown
(ContextualWisdomLab/.github#2148, #2165). These tests cover: parsing
``Retry-After``/``x-ratelimit-reset*``, skipping (and recording) currently
cooled-down candidates without ever excluding an unknown cooldown, waiting out
a storm within budget, failing honestly with ``429``/``provider_rate_limited``
when the budget can't cover it, and keeping a 429 out of the health circuit
breaker.
"""

from __future__ import annotations

import email.utils
import http.client
import io
import json
import threading
import time
import urllib.error
from contextlib import contextmanager
from copy import deepcopy
from email.message import Message
from typing import Any

import pytest

from contextual_orchestrator import ModelAgent, ReasoningEffortProfile, TaskOrchestrator
from contextual_orchestrator.orchestrator import ModelClient
from contextual_orchestrator.provider_errors import (
    PROVIDER_RATE_LIMITED_CODE,
    ProviderUpstreamError,
    parse_retry_after,
    resolve_retry_after_seconds,
)
from contextual_orchestrator.server import SecurityConfig, build_server


def _headers(pairs: dict[str, str] | None = None) -> Message:
    message = Message()
    for name, value in (pairs or {}).items():
        message[name] = value
    return message


def _rate_limited_error(status: int = 429, headers: dict[str, str] | None = None) -> urllib.error.HTTPError:
    body = io.BytesIO(json.dumps({"error": {"message": "rate limited"}}).encode("utf-8"))
    return urllib.error.HTTPError(
        "https://provider.example/v1", status, "rate limited", _headers(headers), body
    )


# --------------------------------------------------------------------------
# Retry-After / x-ratelimit-reset* parsing
# --------------------------------------------------------------------------


def test_parse_retry_after_delta_seconds() -> None:
    assert parse_retry_after("5") == 5.0


def test_parse_retry_after_http_date() -> None:
    now = time.time()
    future = email.utils.format_datetime(
        email.utils.parsedate_to_datetime(email.utils.formatdate(now + 10, usegmt=True))
    )
    seconds = parse_retry_after(future, now=now)
    assert seconds is not None
    assert 9.0 <= seconds <= 11.0


def test_parse_retry_after_missing_or_unparseable_is_unknown() -> None:
    assert parse_retry_after(None) is None
    assert parse_retry_after("") is None
    assert parse_retry_after("not-a-value") is None


def test_resolve_retry_after_prefers_retry_after_header() -> None:
    exc = _rate_limited_error(headers={"Retry-After": "3", "x-ratelimit-reset": "99"})
    assert resolve_retry_after_seconds(exc) == 3.0


def test_resolve_retry_after_falls_back_to_ratelimit_reset_header() -> None:
    exc = _rate_limited_error(headers={"x-ratelimit-reset-requests": "7"})
    assert resolve_retry_after_seconds(exc) == 7.0


def test_resolve_retry_after_unknown_when_neither_header_present() -> None:
    exc = _rate_limited_error(headers={})
    assert resolve_retry_after_seconds(exc) is None


# --------------------------------------------------------------------------
# Candidate selection: skip a known cooldown, never skip an unknown one
# --------------------------------------------------------------------------


class SequencedRateLimitClient:
    """Return one queued outcome per call to ``proxy_send_once`` for an agent."""

    def __init__(self, outcomes: dict[str, list[dict[str, Any] | BaseException]]) -> None:
        self.outcomes = {key: list(value) for key, value in outcomes.items()}
        self.calls: list[str] = []

    def proxy_send_once(self, agent: ModelAgent, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        del endpoint, payload
        self.calls.append(agent.id)
        queue = self.outcomes[agent.id]
        outcome = queue.pop(0) if queue else RuntimeError(f"no more outcomes for {agent.id}")
        if isinstance(outcome, BaseException):
            raise outcome
        return deepcopy(outcome)

    proxy_send = proxy_send_once

    @contextmanager
    def request_settings(self, **overrides: Any):
        del overrides
        yield

    def apply_effort_profile(
        self,
        agent: ModelAgent,
        payload: dict[str, Any],
        profile: ReasoningEffortProfile,
        *,
        api_surface: str = "chat.completions",
    ) -> dict[str, Any]:
        return ModelClient().apply_effort_profile(agent, payload, profile, api_surface=api_surface)


def _two_agent_pool(client: SequencedRateLimitClient, **kwargs: Any) -> TaskOrchestrator:
    return TaskOrchestrator(
        [
            ModelAgent("primary_agent", "primary-model", priority=10, provider_name="primary"),
            ModelAgent("fallback_agent", "fallback-model", priority=1, provider_name="fallback"),
        ],
        client=client,
        **kwargs,
    )


def test_currently_cooled_down_candidate_is_skipped_and_recorded_as_evidence() -> None:
    client = SequencedRateLimitClient(
        {"fallback_agent": [{"id": "chatcmpl_1", "choices": []}]}
    )
    orchestrator = _two_agent_pool(client)
    # Pre-seed a known, still-active cooldown on the primary candidate.
    orchestrator._record_rate_limit("primary_agent", 30.0)

    result = orchestrator.proxy_completion(
        {"model": "orchestrator/auto", "messages": [{"role": "user", "content": "hi"}]}
    )

    assert client.calls == ["fallback_agent"]
    assert result["orchestration"]["rate_limited_skipped"] == ["primary_agent"]


def test_unknown_cooldown_candidate_is_not_skipped() -> None:
    client = SequencedRateLimitClient(
        {"primary_agent": [{"id": "chatcmpl_1", "choices": []}]}
    )
    orchestrator = _two_agent_pool(client)
    # An unknown retry-after (None) must never be recorded as a cooldown.
    orchestrator._record_rate_limit("primary_agent", None)

    result = orchestrator.proxy_completion(
        {"model": "orchestrator/auto", "messages": [{"role": "user", "content": "hi"}]}
    )

    assert client.calls == ["primary_agent"]
    assert "orchestration" not in result or "rate_limited_skipped" not in result.get(
        "orchestration", {}
    )


def test_failover_candidates_shared_helper_skips_rate_limited_by_default() -> None:
    """route_once/conduct's shared ``_failover_candidates`` call also skips cooldowns."""
    client = SequencedRateLimitClient({})
    orchestrator = _two_agent_pool(client)
    orchestrator._record_rate_limit("primary_agent", 30.0)
    primary = orchestrator._agent("primary_agent")

    candidates = orchestrator._failover_candidates(primary, "task text", "worker")

    assert [candidate.id for candidate in candidates] == ["fallback_agent"]


def test_failover_candidates_falls_back_to_full_list_when_all_rate_limited() -> None:
    """A caller with no storm-wait logic still gets one honest attempt, not zero candidates."""
    client = SequencedRateLimitClient({})
    orchestrator = _two_agent_pool(client)
    orchestrator._record_rate_limit("primary_agent", 30.0)
    orchestrator._record_rate_limit("fallback_agent", 30.0)
    primary = orchestrator._agent("primary_agent")

    candidates = orchestrator._failover_candidates(primary, "task text", "worker")

    assert {candidate.id for candidate in candidates} == {"primary_agent", "fallback_agent"}


# --------------------------------------------------------------------------
# Storm with budget: wait out a short cooldown and succeed on retry
# --------------------------------------------------------------------------


def test_storm_with_budget_waits_and_succeeds_on_retry() -> None:
    """Both candidates are 429'd with a 1s Retry-After; a 5s budget waits it out.

    The wait is real (bounded to ~1s -- the codebase's injectable
    ``_rate_limit_sleep`` seam exists for the no-wait-possible case below, but
    faking it here would desynchronize it from the real monotonic clock the
    cooldown itself is measured against), so this asserts elapsed time stays
    small instead of mocking the clock.
    """
    client = SequencedRateLimitClient(
        {
            "primary_agent": [
                _rate_limited_error(headers={"Retry-After": "1"}),
                {"id": "chatcmpl_ok", "choices": []},
            ],
            "fallback_agent": [
                _rate_limited_error(headers={"Retry-After": "1"}),
            ],
        }
    )
    orchestrator = _two_agent_pool(client, rate_limit_wait_seconds=5.0)

    started = time.monotonic()
    result = orchestrator.proxy_completion(
        {"model": "orchestrator/auto", "messages": [{"role": "user", "content": "hi"}]}
    )
    elapsed = time.monotonic() - started

    assert result["id"] == "chatcmpl_ok"
    assert elapsed < 3.0
    assert client.calls.count("primary_agent") == 2
    assert client.calls.count("fallback_agent") == 1
    assert result["orchestration"]["rate_limited_skipped"]
    # A 429 must not trip the circuit breaker for either candidate.
    assert orchestrator._circuit == {}


# --------------------------------------------------------------------------
# Storm without budget: honest 429 to the caller
# --------------------------------------------------------------------------


def test_storm_without_budget_raises_provider_rate_limited() -> None:
    client = SequencedRateLimitClient(
        {
            "primary_agent": [_rate_limited_error(headers={"Retry-After": "30"})],
            "fallback_agent": [_rate_limited_error(headers={"Retry-After": "45"})],
        }
    )
    orchestrator = _two_agent_pool(client, rate_limit_wait_seconds=1.0)
    orchestrator._rate_limit_sleep = lambda seconds: pytest.fail(
        "must not sleep when the budget cannot cover any cooldown"
    )

    with pytest.raises(ProviderUpstreamError) as excinfo:
        orchestrator.proxy_completion(
            {"model": "orchestrator/auto", "messages": [{"role": "user", "content": "hi"}]}
        )

    assert excinfo.value.error_code == PROVIDER_RATE_LIMITED_CODE
    assert excinfo.value.client_status == 429
    assert excinfo.value.retryable is True
    assert excinfo.value.extra_detail["retry_after_seconds"] == pytest.approx(30.0, abs=0.5)
    # Neither candidate's transport failure trips the health circuit breaker.
    assert orchestrator._circuit == {}


def test_storm_without_budget_http_level_returns_429_with_retry_after_header() -> None:
    """server.py surfaces the honest 429 + Retry-After for PROVIDER_RATE_LIMITED_CODE.

    ``proxy_completion``'s multi-candidate virtual-selector loop is reachable
    over HTTP only through direct API use, not ``/v1/chat/completions``
    (a virtual model + tools deliberately stays on Fugu route / TRINITY-
    Conductor conduct instead of single-agent passthrough --
    ``test_http_virtual_free_tools_stay_on_route`` in
    ``tests/test_actions_model_fallback.py``). The single HTTP call site that
    reaches ``proxy_completion`` (``single_agent=True`` tool-loop passthrough)
    only takes a concrete, sticky model with no cross-provider failover, so it
    cannot itself reproduce a multi-candidate storm. This test instead proves
    the HTTP-layer plumbing this PR adds in ``server.py``
    (``_send_error``/``_provider_upstream_extra_headers``): once
    ``proxy_completion`` raises the honest rate-limit-storm error (fully
    exercised at the orchestrator level by the tests above), the HTTP
    response is 429 with a ``Retry-After`` header and
    ``error.code == "provider_rate_limited"``.
    """
    orchestrator = TaskOrchestrator(
        [ModelAgent("worker_one", "worker-model", provider_name="primary")]
    )

    def _raise_storm(*args: Any, **kwargs: Any) -> dict[str, Any]:
        from contextual_orchestrator.provider_errors import rate_limited_storm_error

        raise rate_limited_storm_error(
            agent_id="worker_one", model="worker-model", retry_after_seconds=12.0
        )

    orchestrator.proxy_completion = _raise_storm  # type: ignore[method-assign]
    server = build_server(orchestrator, port=0, security=SecurityConfig(auth_token="unit-token"))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    connection = http.client.HTTPConnection(*server.server_address, timeout=20)
    try:
        body = {
            "model": "worker-model",
            "messages": [{"role": "user", "content": "hi"}],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "noop",
                        "description": "no-op",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            ],
        }
        connection.request(
            "POST",
            "/v1/chat/completions",
            json.dumps(body),
            {
                "Content-Type": "application/json",
                "Authorization": "Bearer unit-token",
            },
        )
        response = connection.getresponse()
        payload = json.loads(response.read().decode())
        assert response.status == 429
        assert response.getheader("retry-after") == "12"
        assert payload["error"]["code"] == PROVIDER_RATE_LIMITED_CODE
    finally:
        connection.close()
        server.shutdown()
        worker.join()
        server.server_close()
        orchestrator.close()


# --------------------------------------------------------------------------
# 429 does not trip the circuit breaker (503 still does)
# --------------------------------------------------------------------------


def test_429_does_not_trip_circuit_breaker_but_503_still_does() -> None:
    client = SequencedRateLimitClient(
        {
            "primary_agent": [_rate_limited_error(status=429, headers={"Retry-After": "1"})],
            "fallback_agent": [{"id": "ok_1", "choices": []}],
        }
    )
    orchestrator = _two_agent_pool(client)

    orchestrator.proxy_completion(
        {"model": "orchestrator/auto", "messages": [{"role": "user", "content": "hi"}]}
    )
    # The 429 attempt against primary_agent must not have opened its breaker.
    assert "primary_agent" not in orchestrator._circuit

    # A direct 503 failure (not quota) is still tracked by the breaker.
    orchestrator._record_failure("primary_agent")
    assert orchestrator._circuit["primary_agent"]["failures"] == 1.0
