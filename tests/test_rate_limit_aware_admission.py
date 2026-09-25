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
from contextual_orchestrator.orchestrator import (
    ModelClient,
    ProviderRequestTooLargeError,
    ProviderResponseError,
)
from contextual_orchestrator.provider_errors import (
    PROVIDER_RATE_LIMITED_CODE,
    ProviderUpstreamError,
    parse_retry_after,
    resolve_retry_after_seconds,
)
from contextual_orchestrator.server import SecurityConfig, build_server
from contextual_orchestrator.tool_fallback import (
    ToolExecutionError,
    ToolFailureKind,
    ToolFallbackStoppedError,
    classify_tool_failure,
)


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
    with _rate_limited_error(headers={"Retry-After": "3", "x-ratelimit-reset": "99"}) as exc:
        assert resolve_retry_after_seconds(exc) == 3.0
    assert exc.closed


def test_resolve_retry_after_falls_back_to_ratelimit_reset_header() -> None:
    with _rate_limited_error(headers={"x-ratelimit-reset-requests": "7"}) as exc:
        assert resolve_retry_after_seconds(exc) == 7.0
    assert exc.closed


def test_resolve_retry_after_unknown_when_neither_header_present() -> None:
    with _rate_limited_error(headers={}) as exc:
        assert resolve_retry_after_seconds(exc) is None
    assert exc.closed


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


def test_unknown_retry_after_assumes_a_short_cooldown_instead_of_recording_nothing() -> None:
    """A 429/503 with no Retry-After/x-ratelimit-reset* must still count as cooling.

    Recording nothing for an unknown duration was the original defect: a
    candidate whose provider omitted the header (RFC 9110 permits this, and
    NIM/OpenRouter routinely do it) was never marked rate-limited, so an
    all-omitted-header storm looked identical to "nothing is rate-limited"
    and failed exactly as if this feature did not exist.
    """
    client = SequencedRateLimitClient(
        {"fallback_agent": [{"id": "chatcmpl_1", "choices": []}]}
    )
    orchestrator = _two_agent_pool(client)
    orchestrator._record_rate_limit("primary_agent", None)

    assert orchestrator._rate_limit_remaining("primary_agent") == pytest.approx(
        orchestrator.rate_limit_unknown_cooldown_seconds, abs=0.5
    )
    assert orchestrator._rate_limit_cooldown_source("primary_agent") == "assumed"

    result = orchestrator.proxy_completion(
        {"model": "orchestrator/auto", "messages": [{"role": "user", "content": "hi"}]}
    )

    assert client.calls == ["fallback_agent"]
    assert result["orchestration"]["rate_limited_skipped"] == ["primary_agent"]


def test_provider_stated_cooldown_is_never_shortened_by_a_later_assumed_one() -> None:
    """The existing 'only extends forward' rule also protects the source label."""
    client = SequencedRateLimitClient({})
    orchestrator = _two_agent_pool(client)
    orchestrator._record_rate_limit("primary_agent", 30.0)
    assert orchestrator._rate_limit_cooldown_source("primary_agent") == "provider"

    # A later, unknown-duration 429 for the same agent must not shorten the
    # active 30s provider-stated cooldown, nor relabel it as "assumed".
    orchestrator._record_rate_limit("primary_agent", None)

    assert orchestrator._rate_limit_remaining("primary_agent") == pytest.approx(30.0, abs=0.5)
    assert orchestrator._rate_limit_cooldown_source("primary_agent") == "provider"


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


# --------------------------------------------------------------------------
# The real orchestrator/free production path: route_once and conduct, which
# both reach a candidate through TaskOrchestrator._invoke via the shared
# _invoke_with_rate_limit_recovery wrapper -- not proxy_completion.
# --------------------------------------------------------------------------


def _rate_limited_upstream_error(retry_after_seconds: float | None) -> ProviderUpstreamError:
    """Build the classified 429 ``_invoke`` sees from ``ModelClient.chat``.

    ``retry_after_seconds=None`` models a provider that stated no
    Retry-After/x-ratelimit-reset* at all (RFC 9110 permits omitting it) --
    ``classify_provider_failure`` never puts the key in ``extra_detail`` for
    that case, so this omits it too rather than passing ``None`` through.
    """
    extra_detail = {} if retry_after_seconds is None else {"retry_after_seconds": retry_after_seconds}
    return ProviderUpstreamError(
        agent_id="unit",
        model="unit-model",
        error_code="rate_limit_exceeded",
        message="rate limited",
        client_status=429,
        provider_status=429,
        retryable=True,
        transport="chat",
        extra_detail=extra_detail,
    )


class QueuedChatOutcomes:
    """Stand in for ``ModelClient.chat``: pop one queued outcome per agent id."""

    def __init__(self, outcomes: dict[str, list[Any]]) -> None:
        self.outcomes = {key: list(value) for key, value in outcomes.items()}
        self.calls: list[str] = []

    def __call__(self, agent: ModelAgent, messages: Any, *args: Any, **kwargs: Any) -> str:
        del messages, args, kwargs
        self.calls.append(agent.id)
        queue = self.outcomes.get(agent.id, [])
        if not queue:
            raise AssertionError(f"no more queued chat outcomes for {agent.id}")
        outcome = queue.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


@pytest.mark.parametrize("primary_review", [True, False])
def test_mixed_free_pool_replay_follows_failed_candidate(primary_review: bool) -> None:
    """A review send stops while an ordinary free candidate can advance."""
    primary = ModelAgent(
        "primary_agent", "primary-model", priority=10,
        tags=("cost:free", "reasoning", "review") if primary_review
        else ("cost:free", "reasoning"),
    )
    fallback = ModelAgent(
        "fallback_agent", "fallback-model", priority=1,
        tags=("cost:free", "reasoning") if primary_review
        else ("cost:free", "reasoning", "review"),
    )
    orchestrator = TaskOrchestrator([primary, fallback], tool_retry_attempts=0)
    failure = ProviderUpstreamError(
        agent_id=primary.id, model=primary.model,
        error_code="rate_limit_exceeded", message="rate limited",
        client_status=429, provider_status=429, retryable=True,
        transport="chat", extra_detail={"retry_after_seconds": 1.0},
    )
    outcomes = QueuedChatOutcomes({primary.id: [failure], fallback.id: ["served"]})
    orchestrator.client.chat = outcomes
    try:
        call = lambda: orchestrator._invoke_with_rate_limit_recovery(
            primary, [{"role": "user", "content": "review"}],
            text="review", role="worker", allowed_agent_ids={primary.id, fallback.id},
            review_no_replay=True, virtual_selector=True,
        )
        if primary_review:
            with pytest.raises(ProviderUpstreamError):
                call()
            assert outcomes.calls == [primary.id]
        else:
            assert call()[0] == "served"
            assert outcomes.calls == [primary.id, fallback.id]
    finally:
        orchestrator.close()


def _free_route_agents() -> list[ModelAgent]:
    return [
        ModelAgent(
            "primary_free_agent",
            "primary-free-model",
            priority=10,
            provider_name="primary",
            tags=("cost:free", "reasoning", "coding"),
        ),
        ModelAgent(
            "fallback_free_agent",
            "fallback-free-model",
            priority=1,
            provider_name="fallback",
            tags=("cost:free", "reasoning", "coding"),
        ),
    ]


def _single_free_agent() -> list[ModelAgent]:
    """A pool with exactly ONE eligible candidate -- a single-route free pool.

    Evidence this shape is real, not hypothetical: noema-review run
    34772771262 on contextual-orchestrator#1177 reported preflight
    ``ready_count: 1``; ContextualWisdomLab/.github#2148 records the
    private-target ZDR pool as three OpenRouter ``:free`` routes on one
    account, so a single 429 can wipe it down to exactly one eligible route.
    """
    return [
        ModelAgent(
            "solo_free_agent",
            "solo-free-model",
            priority=10,
            provider_name="solo",
            tags=("cost:free", "reasoning", "coding"),
        ),
    ]


def _post_chat_completion(port: int, payload: dict[str, Any], token: str):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
    try:
        connection.request(
            "POST",
            "/v1/chat/completions",
            json.dumps(payload),
            {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
                "Connection": "close",
            },
        )
        response = connection.getresponse()
        body = json.loads(response.read().decode())
        return response.status, body, response
    finally:
        connection.close()


def test_http_route_once_waits_out_storm_and_serves_the_request() -> None:
    """orchestrator/free over /v1/chat/completions (route_once) waits out a 429 storm."""
    orchestrator = TaskOrchestrator(
        _free_route_agents(), tool_retry_attempts=0, rate_limit_wait_seconds=5.0
    )
    slept: list[float] = []
    orchestrator._rate_limit_sleep = slept.append
    chat_outcomes = QueuedChatOutcomes(
        {
            "primary_free_agent": [_rate_limited_upstream_error(1.0), "served after wait"],
            "fallback_free_agent": [_rate_limited_upstream_error(1.0)],
        }
    )
    orchestrator.client.chat = chat_outcomes
    token = "unit-token"  # noqa: S105
    server = build_server(orchestrator, port=0, security=SecurityConfig(auth_token=token))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        status, body, _response = _post_chat_completion(
            server.server_address[1],
            {
                "model": TaskOrchestrator.FREE_MODEL,
                "messages": [{"role": "user", "content": "hello"}],
            },
            token,
        )
    finally:
        server.shutdown()
        worker.join(timeout=5)
        server.server_close()
        orchestrator.close()

    assert status == 200, body
    assert body["choices"][0]["message"]["content"] == "served after wait"
    route = body["orchestration"]["route"]
    assert route["terminal_reason"] == "served"
    assert [attempt["outcome"] for attempt in route["attempted"]] == [
        "retryable_transport",
        "retryable_transport",
        "served",
    ]
    assert slept == [pytest.approx(1.0, abs=0.5)]
    assert chat_outcomes.calls.count("primary_free_agent") == 2
    assert chat_outcomes.calls.count("fallback_free_agent") == 1


def test_route_once_preserves_recovered_attempts_on_malformed_exhaustion() -> None:
    """A post-recovery malformed pool keeps both rounds in the final receipt."""
    orchestrator = TaskOrchestrator(
        _free_route_agents(), tool_retry_attempts=0, rate_limit_wait_seconds=5.0
    )
    slept: list[float] = []
    orchestrator._rate_limit_sleep = slept.append
    chat_outcomes = QueuedChatOutcomes(
        {
            "primary_free_agent": [
                _rate_limited_upstream_error(1.0),
                ProviderResponseError("malformed primary response"),
            ],
            "fallback_free_agent": [
                _rate_limited_upstream_error(1.0),
                ProviderResponseError("malformed fallback response"),
            ],
        }
    )
    orchestrator.client.chat = chat_outcomes

    with pytest.raises(ProviderResponseError) as excinfo:
        orchestrator.route_once(
            [{"role": "user", "content": "hello"}],
            model_name=TaskOrchestrator.FREE_MODEL,
        )

    route = excinfo.value.detail["route"]
    assert route["eligible_agent_ids"] == [
        "primary_free_agent",
        "fallback_free_agent",
    ]
    assert [attempt["outcome"] for attempt in route["attempted"]] == [
        "retryable_transport",
        "retryable_transport",
        "fail_closed",
        "fail_closed",
    ]
    assert route["terminal_reason"] == "eligible_set_exhausted"
    assert slept == [pytest.approx(1.0, abs=0.5)]
    orchestrator.close()


def _service_unavailable(retry_after_seconds: float) -> ProviderUpstreamError:
    """Classified 503 the chat transport already handed to ``_invoke``."""
    return ProviderUpstreamError(
        agent_id="unit",
        model="unit-model",
        error_code="service_unavailable",
        message="upstream unavailable",
        client_status=503,
        provider_status=503,
        retryable=True,
        transport="chat",
        extra_detail={"retry_after_seconds": retry_after_seconds},
    )


def _ambiguous_tool_stop() -> ToolExecutionError:
    return ToolExecutionError(
        "request may have completed token=must-not-leak",
        tool_name="send_message",
        kind=ToolFailureKind.TRANSPORT_ERROR,
        outcome_unknown=True,
    )


def test_http_fail_closed_after_503_keeps_route_and_stops() -> None:
    """HTTP 409 keeps the earlier 503 and the terminal tool stop, then stops."""
    agents = [
        *_free_route_agents(),
        ModelAgent(
            "untried_free_agent",
            "untried-free-model",
            priority=0,
            provider_name="untried",
            tags=("cost:free", "reasoning", "coding"),
        ),
    ]
    orchestrator = TaskOrchestrator(agents, tool_retry_attempts=0)
    chat_outcomes = QueuedChatOutcomes(
        {
            "primary_free_agent": [_service_unavailable(1.0)],
            "fallback_free_agent": [_ambiguous_tool_stop()],
            "untried_free_agent": ["must not run"],
        }
    )
    orchestrator.client.chat = chat_outcomes
    token = "unit-token"  # noqa: S105
    server = build_server(orchestrator, port=0, security=SecurityConfig(auth_token=token))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    response = None
    try:
        status, body, response = _post_chat_completion(
            server.server_address[1],
            {
                "model": TaskOrchestrator.FREE_MODEL,
                "messages": [{"role": "user", "content": "hello"}],
            },
            token,
        )
    finally:
        if response is not None:
            response.close()
        server.shutdown()
        worker.join(timeout=5)
        server.server_close()
        orchestrator.close()

    assert response is not None and response.closed
    assert status == 409, body
    assert body["error"]["code"] == "tool_execution_stopped"
    assert body["error"]["detail"]["failure_kind"] == "ambiguous_outcome"
    route = body["error"]["detail"]["route"]
    assert route["eligible_agent_ids"] == [
        "primary_free_agent",
        "fallback_free_agent",
        "untried_free_agent",
    ]
    assert [attempt["outcome"] for attempt in route["attempted"]] == [
        "retryable_transport",
        "fail_closed",
    ]
    terminal = route["attempted"][-1]
    assert "error_code" not in terminal
    assert "provider_status" not in terminal
    assert [attempt["agent_id"] for attempt in route["attempted"]] == [
        "primary_free_agent",
        "fallback_free_agent",
    ]
    assert route["terminal_reason"] == "fail_closed"
    assert chat_outcomes.calls == ["primary_free_agent", "fallback_free_agent"]
    assert "must-not-leak" not in json.dumps(body)


def test_route_once_fail_closed_keeps_attempts_from_the_wait_round(monkeypatch) -> None:
    """A tool stop after a 503 storm still carries the waited round's attempts."""
    orchestrator = TaskOrchestrator(
        _free_route_agents(), tool_retry_attempts=0, rate_limit_wait_seconds=5.0
    )
    slept: list[float] = []
    now = [100.0]
    monkeypatch.setattr(time, "monotonic", lambda: now[0])

    def advance_clock(seconds: float) -> None:
        slept.append(seconds)
        now[0] += seconds

    orchestrator._rate_limit_sleep = advance_clock
    chat_outcomes = QueuedChatOutcomes(
        {
            "primary_free_agent": [
                _service_unavailable(0.01),
                _service_unavailable(0.01),
            ],
            "fallback_free_agent": [
                _service_unavailable(0.01),
                _ambiguous_tool_stop(),
            ],
        }
    )
    orchestrator.client.chat = chat_outcomes

    with pytest.raises(ToolFallbackStoppedError) as excinfo:
        orchestrator.route_once(
            [{"role": "user", "content": "hello"}],
            model_name=TaskOrchestrator.FREE_MODEL,
        )

    assert type(excinfo.value) is ToolFallbackStoppedError
    route = excinfo.value.detail["route"]
    assert route["terminal_reason"] == "fail_closed"
    assert [attempt["outcome"] for attempt in route["attempted"]] == [
        "retryable_transport",
        "retryable_transport",
        "retryable_transport",
        "fail_closed",
    ]
    assert chat_outcomes.calls == [
        "primary_free_agent",
        "fallback_free_agent",
        "primary_free_agent",
        "fallback_free_agent",
    ]
    assert slept == [pytest.approx(0.01, abs=0.5)]
    orchestrator.close()


def test_route_once_preserves_attempts_across_judge_rejected_worker_rounds() -> None:
    """A later direct worker success must not erase an earlier failover receipt."""
    orchestrator = TaskOrchestrator(_free_route_agents(), tool_retry_attempts=1)
    chat_outcomes = QueuedChatOutcomes(
        {
            "primary_free_agent": [
                _rate_limited_upstream_error(1.0),
                _rate_limited_upstream_error(1.0),
            ],
            "fallback_free_agent": ["first answer", "second answer"],
        }
    )
    orchestrator.client.chat = chat_outcomes
    judge_results = iter((False, True))

    def judge_worker_answer(**kwargs: Any) -> dict[str, Any]:
        del kwargs
        accepted = next(judge_results)
        return {
            "accepted": accepted,
            "reason": "accepted" if accepted else "retry another worker",
            "verifier_output": "",
            "judge": "model",
        }

    orchestrator._realtime_route_judge = judge_worker_answer  # type: ignore[method-assign]

    result = orchestrator.route_once(
        [{"role": "user", "content": "hello"}],
        model_name=TaskOrchestrator.FREE_MODEL,
    )

    assert result["answer"] == "second answer"
    assert result["route"]["eligible_agent_ids"] == [
        "primary_free_agent",
        "fallback_free_agent",
    ]
    assert [attempt["outcome"] for attempt in result["route"]["attempted"]] == [
        "retryable_transport",
        "retryable_transport",
        "served",
        "served",
    ]
    assert result["route"]["terminal_reason"] == "served"
    orchestrator.close()


@pytest.mark.parametrize("malformed_agent_id", ["primary_free_agent", "fallback_free_agent"])
def test_route_once_preserves_malformed_taxonomy_for_mixed_size_exhaustion(
    malformed_agent_id: str,
) -> None:
    """A mixed malformed/413 pool keeps the fail-closed response taxonomy."""
    orchestrator = TaskOrchestrator(_free_route_agents(), tool_retry_attempts=0)
    size_agent_id = (
        "fallback_free_agent"
        if malformed_agent_id == "primary_free_agent"
        else "primary_free_agent"
    )
    orchestrator.client.chat = QueuedChatOutcomes(
        {
            malformed_agent_id: [ProviderResponseError("malformed provider response")],
            size_agent_id: [ProviderRequestTooLargeError("provider limit exceeded")],
        }
    )

    with pytest.raises(ProviderResponseError) as excinfo:
        orchestrator.route_once(
            [{"role": "user", "content": "large structured request"}],
            model_name=TaskOrchestrator.FREE_MODEL,
        )

    route = excinfo.value.detail["route"]
    assert route["eligible_agent_ids"] == [
        "primary_free_agent",
        "fallback_free_agent",
    ]
    assert [attempt["outcome"] for attempt in route["attempted"]] == (
        ["fail_closed", "request_too_large"]
        if malformed_agent_id == "primary_free_agent"
        else ["request_too_large", "fail_closed"]
    )
    assert route["terminal_reason"] == "eligible_set_exhausted"
    orchestrator.close()


def _default_route_agents() -> list[ModelAgent]:
    """Two ungrouped workers so a default/auto route failsover with no allow-list."""
    return [
        ModelAgent(
            "primary_worker",
            "primary-model",
            priority=10,
            tags=("reasoning", "writing"),
        ),
        ModelAgent(
            "fallback_worker",
            "fallback-model",
            priority=1,
            tags=("reasoning", "writing"),
        ),
    ]


def _wrapped_provider_tool_stop(agent_id: str) -> ToolFallbackStoppedError:
    """The already-wrapped stop ``_provider_tool_execution_stopped`` returns."""
    decision = classify_tool_failure(
        ToolExecutionError(
            "provider reported terminal tool execution state",
            tool_name="provider_tool_runtime",
            kind=ToolFailureKind.TRANSPORT_ERROR,
            outcome_unknown=True,
        )
    )
    return ToolFallbackStoppedError(agent_id, decision)


@pytest.mark.parametrize(
    "model_name",
    [TaskOrchestrator.AUTO_MODEL, TaskOrchestrator.GATEWAY_DEFAULT_MODEL],
)
def test_default_route_malformed_after_failover_keeps_response_route(
    model_name: str,
) -> None:
    """A default/auto failover must attach route before rethrowing a malformed response."""
    orchestrator = TaskOrchestrator(_default_route_agents(), tool_retry_attempts=0)
    orchestrator.client.chat = QueuedChatOutcomes(
        {
            "primary_worker": [_service_unavailable(1.0)],
            "fallback_worker": [ProviderResponseError("malformed fallback response")],
        }
    )

    with pytest.raises(ProviderResponseError) as excinfo:
        orchestrator.route_once(
            [{"role": "user", "content": "hello"}],
            model_name=model_name,
        )

    assert type(excinfo.value) is ProviderResponseError
    route = excinfo.value.detail["route"]
    assert [row["agent_id"] for row in route["attempted"]] == [
        "primary_worker",
        "fallback_worker",
    ]
    assert [row["outcome"] for row in route["attempted"]] == [
        "retryable_transport",
        "fail_closed",
    ]
    assert route["terminal_reason"] == "fail_closed"
    orchestrator.close()


@pytest.mark.parametrize(
    "model_name",
    [TaskOrchestrator.AUTO_MODEL, TaskOrchestrator.GATEWAY_DEFAULT_MODEL],
)
def test_default_route_wrapped_tool_stop_keeps_prior_attempts(
    model_name: str,
) -> None:
    """An already-wrapped provider tool stop still carries the prior failover row."""
    orchestrator = TaskOrchestrator(_default_route_agents(), tool_retry_attempts=0)
    orchestrator.client.chat = QueuedChatOutcomes(
        {
            "primary_worker": [_service_unavailable(1.0)],
            "fallback_worker": [_wrapped_provider_tool_stop("fallback_worker")],
        }
    )

    with pytest.raises(ToolFallbackStoppedError) as excinfo:
        orchestrator.route_once(
            [{"role": "user", "content": "hello"}],
            model_name=model_name,
        )

    route = excinfo.value.detail["route"]
    assert [row["outcome"] for row in route["attempted"]] == [
        "retryable_transport",
        "fail_closed",
    ]
    terminal = route["attempted"][-1]
    assert terminal["agent_id"] == "fallback_worker"
    assert "error_code" not in terminal
    assert "provider_status" not in terminal
    assert route["terminal_reason"] == "fail_closed"
    orchestrator.close()


def test_http_route_once_all_size_exhaustion_preserves_route_evidence() -> None:
    """The special HTTP 413 handler exposes the route receipt attached by the owner."""
    orchestrator = TaskOrchestrator(_free_route_agents(), tool_retry_attempts=0)
    orchestrator.client.chat = QueuedChatOutcomes(
        {
            "primary_free_agent": [
                ProviderRequestTooLargeError("primary provider limit exceeded")
            ],
            "fallback_free_agent": [
                ProviderRequestTooLargeError("fallback provider limit exceeded")
            ],
        }
    )
    token = "unit-token"  # noqa: S105
    server = build_server(orchestrator, port=0, security=SecurityConfig(auth_token=token))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        status, body, _response = _post_chat_completion(
            server.server_address[1],
            {
                "model": TaskOrchestrator.FREE_MODEL,
                "messages": [{"role": "user", "content": "large request"}],
            },
            token,
        )
    finally:
        server.shutdown()
        worker.join(timeout=5)
        server.server_close()
        orchestrator.close()

    assert status == 413
    assert body["error"]["code"] == "request_too_large"
    route = body["error"]["detail"]["route"]
    assert route["eligible_agent_ids"] == [
        "primary_free_agent",
        "fallback_free_agent",
    ]
    assert [attempt["outcome"] for attempt in route["attempted"]] == [
        "request_too_large",
        "request_too_large",
    ]
    assert route["terminal_reason"] == "request_too_large_exhausted"


def test_http_route_once_storm_without_budget_returns_429() -> None:
    """Same storm with no wait budget: honest 429 + Retry-After on the route_once path."""
    orchestrator = TaskOrchestrator(
        _free_route_agents(), tool_retry_attempts=0, rate_limit_wait_seconds=0.0
    )
    chat_outcomes = QueuedChatOutcomes(
        {
            "primary_free_agent": [_rate_limited_upstream_error(9.0)],
            "fallback_free_agent": [_rate_limited_upstream_error(9.0)],
        }
    )
    orchestrator.client.chat = chat_outcomes
    token = "unit-token"  # noqa: S105
    server = build_server(orchestrator, port=0, security=SecurityConfig(auth_token=token))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        status, body, response = _post_chat_completion(
            server.server_address[1],
            {
                "model": TaskOrchestrator.FREE_MODEL,
                "messages": [{"role": "user", "content": "hello"}],
            },
            token,
        )
    finally:
        server.shutdown()
        worker.join(timeout=5)
        server.server_close()
        orchestrator.close()

    assert status == 429, body
    assert response.getheader("retry-after") == "9"
    assert body["error"]["code"] == PROVIDER_RATE_LIMITED_CODE
    assert body["error"]["detail"]["route"]["eligible_agent_ids"] == [
        "primary_free_agent",
        "fallback_free_agent",
    ]
    assert [
        attempt["outcome"]
        for attempt in body["error"]["detail"]["route"]["attempted"]
    ] == ["retryable_transport", "retryable_transport"]
    assert (
        body["error"]["detail"]["route"]["terminal_reason"]
        == "rate_limit_wait_budget_exhausted"
    )


def test_http_route_once_storm_with_no_retry_after_waits_the_assumed_cooldown() -> None:
    """Every candidate 429s with NO Retry-After/x-ratelimit-reset*: still waits and is served.

    This is the shape the coordinator flagged as the remaining defect: a
    provider (NIM/OpenRouter routinely do this) that returns 429/503 with no
    cooldown header at all must not be treated as "not rate-limited" --
    _record_rate_limit now assumes rate_limit_unknown_cooldown_seconds
    instead of recording nothing.
    """
    orchestrator = TaskOrchestrator(
        _free_route_agents(),
        tool_retry_attempts=0,
        rate_limit_wait_seconds=5.0,
        rate_limit_unknown_cooldown_seconds=1.0,
    )
    chat_outcomes = QueuedChatOutcomes(
        {
            "primary_free_agent": [_rate_limited_upstream_error(None), "served after wait"],
            "fallback_free_agent": [_rate_limited_upstream_error(None)],
        }
    )
    orchestrator.client.chat = chat_outcomes
    token = "unit-token"  # noqa: S105
    server = build_server(orchestrator, port=0, security=SecurityConfig(auth_token=token))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        started = time.monotonic()
        status, body, _response = _post_chat_completion(
            server.server_address[1],
            {
                "model": TaskOrchestrator.FREE_MODEL,
                "messages": [{"role": "user", "content": "hello"}],
            },
            token,
        )
        elapsed = time.monotonic() - started
    finally:
        server.shutdown()
        worker.join(timeout=5)
        server.server_close()
        orchestrator.close()

    assert status == 200, body
    assert body["choices"][0]["message"]["content"] == "served after wait"
    assert elapsed < 3.0
    assert chat_outcomes.calls.count("primary_free_agent") == 2
    assert chat_outcomes.calls.count("fallback_free_agent") == 1


def test_http_route_once_storm_with_no_retry_after_and_no_budget_returns_429_assumed() -> None:
    """Same no-Retry-After storm with zero budget: honest 429 labeled ``cooldown_source: assumed``."""
    orchestrator = TaskOrchestrator(
        _free_route_agents(),
        tool_retry_attempts=0,
        rate_limit_wait_seconds=0.0,
        rate_limit_unknown_cooldown_seconds=4.0,
    )
    chat_outcomes = QueuedChatOutcomes(
        {
            "primary_free_agent": [_rate_limited_upstream_error(None)],
            "fallback_free_agent": [_rate_limited_upstream_error(None)],
        }
    )
    orchestrator.client.chat = chat_outcomes
    token = "unit-token"  # noqa: S105
    server = build_server(orchestrator, port=0, security=SecurityConfig(auth_token=token))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        status, body, response = _post_chat_completion(
            server.server_address[1],
            {
                "model": TaskOrchestrator.FREE_MODEL,
                "messages": [{"role": "user", "content": "hello"}],
            },
            token,
        )
    finally:
        server.shutdown()
        worker.join(timeout=5)
        server.server_close()
        orchestrator.close()

    assert status == 429, body
    assert response.getheader("retry-after") == "4"
    assert body["error"]["code"] == PROVIDER_RATE_LIMITED_CODE
    assert body["error"]["detail"]["cooldown_source"] == "assumed"


def test_conduct_worker_step_waits_out_storm_and_serves_the_request() -> None:
    """A conduct (deep-path) request's worker step waits out the same storm."""
    agents = [
        ModelAgent(
            "primary_agent",
            "primary-model",
            priority=10,
            provider_name="primary",
            tags=(
                "cost:free",
                "planning", "reasoning", "research",
                "verification", "security", "debugging",
                "writing",
                "coding", "implementation",
            ),
        ),
        ModelAgent(
            "fallback_agent",
            "fallback-model",
            priority=1,
            provider_name="fallback",
            tags=("cost:free", "coding", "implementation", "reasoning"),
        ),
    ]
    orchestrator = TaskOrchestrator(agents, tool_retry_attempts=0, rate_limit_wait_seconds=5.0)
    chat_outcomes = QueuedChatOutcomes(
        {
            "primary_agent": [
                "thinker plan",
                _rate_limited_upstream_error(1.0),
                "worker output after wait",
                "verifier output",
                "synthesizer output",
            ],
            "fallback_agent": [_rate_limited_upstream_error(1.0)],
        }
    )
    orchestrator.client.chat = chat_outcomes

    started = time.monotonic()
    result = orchestrator.conduct(
        [{"role": "user", "content": "do the task"}],
        model_name=TaskOrchestrator.FREE_MODEL,
    )
    elapsed = time.monotonic() - started

    # The request completes (no exception) with every step served, including
    # the worker step that hit -- and waited out -- the storm. Whether the
    # verifier's own (unrelated, judge-heuristic) verdict later prefers the
    # worker's or the synthesizer's text as the final "answer" is not part of
    # this admission contract, so this only pins the worker step itself.
    assert elapsed < 3.0
    worker_step = next(row for row in result["trace"] if row["role"] == "worker")
    assert worker_step["output"] == "worker output after wait"
    synthesizer_step = next(row for row in result["trace"] if row["role"] == "synthesizer")
    assert synthesizer_step["output"] == "synthesizer output"
    assert chat_outcomes.calls.count("primary_agent") == 5
    assert chat_outcomes.calls.count("fallback_agent") == 1
    orchestrator.close()


# --------------------------------------------------------------------------
# Explicit-vs-virtual selector, not candidate count: a virtual selector must
# wait even with exactly ONE eligible candidate; an explicit concrete model
# must still fail fast regardless of candidate count.
# --------------------------------------------------------------------------


def test_virtual_selector_single_candidate_storm_waits_and_serves() -> None:
    """FREE_MODEL with exactly one eligible candidate still waits out a storm.

    Regression coverage for the defect fixed in this entry:
    ``_await_rate_limit_recovery`` used to open with
    ``if len(candidates) < 2: return False``, so a single-eligible-candidate
    virtual pool (the shape noema-review run 34772771262 hit on
    contextual-orchestrator#1177, preflight ``ready_count: 1``) failed
    immediately instead of waiting out the storm. Uses the codebase's
    injectable ``_rate_limit_sleep`` seam so the assumed-cooldown wait is
    fake, not a real multi-second sleep.
    """
    orchestrator = TaskOrchestrator(
        _single_free_agent(), tool_retry_attempts=0, rate_limit_wait_seconds=5.0
    )
    slept: list[float] = []
    orchestrator._rate_limit_sleep = slept.append
    chat_outcomes = QueuedChatOutcomes(
        {
            "solo_free_agent": [
                _rate_limited_upstream_error(1.0),
                "served after wait",
            ],
        }
    )
    orchestrator.client.chat = chat_outcomes

    result = orchestrator.route_once(
        [{"role": "user", "content": "hello"}],
        model_name=TaskOrchestrator.FREE_MODEL,
    )

    assert result["answer"] == "served after wait"
    assert chat_outcomes.calls.count("solo_free_agent") == 2
    assert slept == [pytest.approx(1.0, abs=0.5)]
    orchestrator.close()


def test_virtual_selector_single_candidate_storm_without_budget_raises_honest_429() -> None:
    """Same single-candidate virtual case with no wait budget: honest 429, not a generic failure."""
    orchestrator = TaskOrchestrator(
        _single_free_agent(), tool_retry_attempts=0, rate_limit_wait_seconds=0.0
    )
    orchestrator._rate_limit_sleep = lambda seconds: pytest.fail(
        "must not sleep when the budget cannot cover the cooldown"
    )
    chat_outcomes = QueuedChatOutcomes(
        {"solo_free_agent": [_rate_limited_upstream_error(9.0)]}
    )
    orchestrator.client.chat = chat_outcomes

    with pytest.raises(ProviderUpstreamError) as excinfo:
        orchestrator.route_once(
            [{"role": "user", "content": "hello"}],
            model_name=TaskOrchestrator.FREE_MODEL,
        )

    assert excinfo.value.error_code == PROVIDER_RATE_LIMITED_CODE
    assert excinfo.value.client_status == 429
    assert excinfo.value.retryable is True
    assert excinfo.value.extra_detail["retry_after_seconds"] == pytest.approx(9.0, abs=0.5)
    orchestrator.close()


def test_explicit_concrete_model_single_candidate_storm_fails_fast_without_waiting() -> None:
    """An explicit concrete model with one always-429 candidate fails fast, unchanged.

    This is the pre-existing contract
    ``tests/test_provider_error_taxonomy.py::test_chat_completions_returns_openai_compatible_rate_limit_error``
    pins: a pinned model must never wait out an assumed cooldown, regardless
    of the (irrelevant, now that selector kind is the discriminator)
    candidate count.
    """
    orchestrator = TaskOrchestrator(
        _single_free_agent(), tool_retry_attempts=0, rate_limit_wait_seconds=5.0
    )
    orchestrator._rate_limit_sleep = lambda seconds: pytest.fail(
        "must not sleep for an explicit concrete model -- fail fast unchanged"
    )
    chat_outcomes = QueuedChatOutcomes(
        {"solo_free_agent": [_rate_limited_upstream_error(1.0)]}
    )
    orchestrator.client.chat = chat_outcomes

    with pytest.raises(ProviderUpstreamError) as excinfo:
        orchestrator.route_once(
            [{"role": "user", "content": "hello"}],
            model_name="solo-free-model",
        )

    assert excinfo.value.provider_status == 429
    assert chat_outcomes.calls.count("solo_free_agent") == 1
    orchestrator.close()
