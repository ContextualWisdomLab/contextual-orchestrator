"""Provider reliability: transient-only retry with backoff, cross-agent failover, circuit breaker.

These exercise the previously untested resilience path of the orchestration engine —
the capability a model-orchestration gateway is bought for.
"""

from __future__ import annotations

import io
import json
import socket
import ssl
import sys
import threading
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import pytest
from dataclasses import replace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.orchestrator import (  # noqa: E402
    TRANSIENT_HTTP_STATUS,
    ModelClient,
    NoViableAgentError,
    ProviderResponseError,
    RequestDeadlineExceeded,
    is_transient_error,
    _is_tool_execution_stopped,
    _provider_limit_contract,
)
import contextual_orchestrator.orchestrator as orchestrator_module
from contextual_orchestrator.tool_fallback import ToolFallbackStoppedError


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://provider.example/chat/completions", code, "err", None, None)


def _stopped_http_error() -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://provider.example/chat/completions",
        409,
        "Conflict",
        None,
        io.BytesIO(json.dumps({"error": {"code": "tool_execution_stopped"}}).encode()),
    )


def test_transient_classification_matches_status_and_network_errors() -> None:
    for code in (408, 409, 425, 429, 500, 502, 503, 504):
        assert code in TRANSIENT_HTTP_STATUS
        assert is_transient_error(_http_error(code)), f"{code} should be transient"
    for code in (400, 401, 403, 404, 422):
        assert not is_transient_error(_http_error(code)), f"{code} must not be retried"
    assert is_transient_error(urllib.error.URLError("dns"))
    assert is_transient_error(TimeoutError("read timeout"))
    assert is_transient_error(socket.timeout("slow"))


def test_http_error_body_is_shared_by_terminal_and_limit_classifiers() -> None:
    error = urllib.error.HTTPError(
        "https://provider.example/v1/embeddings", 413, "large", {},
        io.BytesIO(json.dumps({"error": {"code": "too_many_inputs", "max_inputs": 2}}).encode()),
    )
    assert not _is_tool_execution_stopped(error)
    assert _provider_limit_contract(error) == ("too_many_inputs", 2, None)


def test_provider_tool_stop_is_terminal_through_chat_and_raw_retry_layers() -> None:
    class StoppedProviderClient(ModelClient):
        def __init__(self) -> None:
            super().__init__(max_retries=3, retry_backoff=0.0)
            self.chat_calls = 0
            self.raw_calls = 0

        def _validate_provider(self, agent: ModelAgent):  # type: ignore[override]
            del agent
            return

        def _send(self, agent, payload, destination=None, *, timeout=None):  # type: ignore[override]
            del agent, payload, destination, timeout
            self.chat_calls += 1
            raise _stopped_http_error()

        def _send_raw(self, agent, endpoint, payload, destination=None):  # type: ignore[override]
            del agent, endpoint, payload, destination
            self.raw_calls += 1
            raise _stopped_http_error()

    client = StoppedProviderClient()
    agent = ModelAgent(
        "provider_worker",
        "provider-model",
        base_url="https://provider.example/v1",
        api_key_env="",
        credential_key="",
    )

    try:
        client.chat(agent, [{"role": "user", "content": "send"}])
    except ToolFallbackStoppedError as exc:
        assert exc.decision.kind.value == "ambiguous_outcome"
    else:  # pragma: no cover
        raise AssertionError("provider tool stop must fail closed")
    try:
        client.proxy_send(agent, "chat/completions", {"model": agent.model, "messages": []})
    except ToolFallbackStoppedError:
        pass
    else:  # pragma: no cover
        raise AssertionError("raw provider tool stop must fail closed")

    assert client.chat_calls == 1
    assert client.raw_calls == 1
    assert is_transient_error(ssl.SSLEOFError("peer closed TLS stream"))
    assert is_transient_error(ssl.SSLSyscallError("SSL_ERROR_SYSCALL"))
    assert not is_transient_error(ssl.SSLCertVerificationError("certificate verify failed"))
    assert not is_transient_error(ValueError("bad json"))


def test_tool_execution_stopped_409_is_terminal_but_generic_conflict_retries() -> None:
    stopped = _stopped_http_error()
    assert not is_transient_error(stopped)
    assert is_transient_error(_http_error(409))


def test_terminal_tool_stop_is_preserved_by_chat_and_passthrough_transport() -> None:
    class StoppedClient(ModelClient):
        def __init__(self) -> None:
            super().__init__(max_retries=3, retry_backoff=0.0)
            self.attempts = 0

        def _send(self, agent: ModelAgent, payload: dict, destination=None) -> str:  # type: ignore[override]
            del agent, payload, destination
            self.attempts += 1
            raise _stopped_http_error()

        def _send_raw(self, agent: ModelAgent, endpoint: str, payload: dict, destination=None) -> dict:  # type: ignore[override]
            del agent, endpoint, payload, destination
            self.attempts += 1
            raise _stopped_http_error()

    client = StoppedClient()
    agent = ModelAgent("worker_agent", "gpt", base_url="https://provider.example/v1")

    with pytest.raises(ToolFallbackStoppedError) as chat_error:
        client._send_with_retry(agent, {"model": agent.model})
    assert chat_error.value.decision.kind.value == "ambiguous_outcome"
    assert chat_error.value.decision.observed_kind.value == "transport_error"
    assert client.attempts == 1

    with pytest.raises(ToolFallbackStoppedError) as passthrough_error:
        client._send_raw_with_retry(agent, "chat/completions", {"model": agent.model})
    assert passthrough_error.value.decision.reason_code == "tool_failure.ambiguous_outcome.fail_closed"
    assert client.attempts == 2


def test_retry_recovers_from_transient_failures_with_backoff() -> None:
    delays: list[float] = []

    class FlakyClient(ModelClient):
        def __init__(self) -> None:
            super().__init__(max_retries=3, retry_backoff=0.1)
            self._sleep = delays.append  # capture backoff instead of sleeping
            self.attempts = 0

        def _send(self, agent: ModelAgent, payload: dict, destination=None) -> str:  # type: ignore[override]
            self.attempts += 1
            if self.attempts < 3:
                raise _http_error(503)
            return "recovered"

    client = FlakyClient()
    agent = ModelAgent("worker_agent", "gpt", base_url="https://provider.example/v1", api_key_env="X")
    result = client._send_with_retry(agent, {"model": "gpt"})
    assert result == "recovered"
    assert client.attempts == 3  # 2 failures + 1 success
    assert len(delays) == 2  # one backoff between each retry
    assert all(0.0 <= d <= client.retry_backoff_cap for d in delays)


def test_local_retry_budget_is_zero_by_default_to_avoid_queue_multiplication() -> None:
    class LocalDownClient(ModelClient):
        def __init__(self) -> None:
            super().__init__(max_retries=5, retry_backoff=0.0)
            self.attempts = 0

        def _send(self, agent: ModelAgent, payload: dict, destination=None) -> str:  # type: ignore[override]
            self.attempts += 1
            raise urllib.error.URLError("local server is busy")

    client = LocalDownClient()
    agent = ModelAgent("local_worker", "local-model", base_url="mlx://127.0.0.1:8080/v1")
    try:
        client._send_with_retry(agent, {"model": agent.model})
    except RuntimeError:
        pass
    else:  # pragma: no cover
        raise AssertionError("a failed local request must not succeed")
    assert client.attempts == 1


def test_local_retry_budget_can_be_explicitly_opted_into() -> None:
    class LocalFlakyClient(ModelClient):
        def __init__(self) -> None:
            super().__init__(max_retries=5, local_max_retries=1, retry_backoff=0.0)
            self.attempts = 0

        def _send(self, agent: ModelAgent, payload: dict, destination=None) -> str:  # type: ignore[override]
            self.attempts += 1
            if self.attempts == 1:
                raise urllib.error.URLError("local server restarted")
            return "recovered"

    client = LocalFlakyClient()
    agent = ModelAgent("local_worker", "local-model", base_url="local://127.0.0.1:8080/v1")
    assert client._send_with_retry(agent, {"model": agent.model}) == "recovered"
    assert client.attempts == 2


def test_local_retry_budget_is_not_capped_by_remote_retry_default() -> None:
    class LocalFlakyClient(ModelClient):
        def __init__(self) -> None:
            super().__init__(max_retries=0, local_max_retries=2, retry_backoff=0.0)
            self.attempts = 0

        def _send(self, agent: ModelAgent, payload: dict, destination=None) -> str:  # type: ignore[override]
            self.attempts += 1
            if self.attempts < 3:
                raise urllib.error.URLError("local server is restarting")
            return "recovered"

    client = LocalFlakyClient()
    agent = ModelAgent("local_worker", "local-model", base_url="mlx://127.0.0.1:8080/v1")
    assert client._send_with_retry(agent, {"model": agent.model}) == "recovered"
    assert client.attempts == 3


def test_local_passthrough_retry_budget_is_not_capped_by_remote_retry_default() -> None:
    class LocalRawFlakyClient(ModelClient):
        def __init__(self) -> None:
            super().__init__(max_retries=0, local_max_retries=2, retry_backoff=0.0)
            self.attempts = 0

        def _send_raw(self, agent: ModelAgent, endpoint: str, payload: dict, destination=None) -> dict:  # type: ignore[override]
            self.attempts += 1
            if self.attempts < 3:
                raise urllib.error.URLError("local server is restarting")
            return {"ok": True}

    client = LocalRawFlakyClient()
    agent = ModelAgent("local_worker", "local-model", base_url="local://127.0.0.1:8080/v1")
    assert client._send_raw_with_retry(agent, "chat/completions", {}) == {"ok": True}
    assert client.attempts == 3


def test_permanent_error_is_not_retried() -> None:
    class BadRequestClient(ModelClient):
        def __init__(self) -> None:
            super().__init__(max_retries=5, retry_backoff=0.0)
            self.attempts = 0

        def _send(self, agent: ModelAgent, payload: dict, destination=None) -> str:  # type: ignore[override]
            self.attempts += 1
            raise _http_error(400)

    client = BadRequestClient()
    agent = ModelAgent("worker_agent", "gpt", base_url="https://provider.example/v1", api_key_env="X")
    raised = False
    try:
        client._send_with_retry(agent, {"model": "gpt"})
    except RuntimeError:
        raised = True
    assert raised
    assert client.attempts == 1  # 400 is a caller error: exactly one attempt, no retry


def test_provider_request_hides_raw_error_text_and_cause() -> None:
    class RawProviderFailureClient(ModelClient):
        def _send(self, agent: ModelAgent, payload: dict, destination=None) -> str:  # type: ignore[override]
            raise RuntimeError("provider-secret-response")

    client = RawProviderFailureClient(max_retries=0)
    agent = ModelAgent("worker_agent", "gpt", base_url="https://provider.example/v1")

    try:
        client._send_with_retry(agent, {"model": "gpt"})
    except RuntimeError as error:
        assert "provider-secret-response" not in str(error)
        assert error.__cause__ is None
    else:  # pragma: no cover
        raise AssertionError("a failed provider request must raise")


class _AgentDownClient(ModelClient):
    """Fails for a chosen agent id, succeeds for the rest."""

    def __init__(self, down_id: str) -> None:
        super().__init__(retry_backoff=0.0)
        self.down_id = down_id
        self.calls: list[str] = []

    def chat(self, agent: ModelAgent, messages: list, temperature: float = 0.2) -> str:  # type: ignore[override]
        self.calls.append(agent.id)
        if agent.id == self.down_id:
            raise RuntimeError(f"{agent.id} unavailable")
        return f"[{agent.id}] answer"


def _two_worker_orchestrator(down_id: str) -> tuple[TaskOrchestrator, _AgentDownClient]:
    agents = [
        ModelAgent("primary_worker", "mock", tags=("reasoning", "writing"), priority=5),
        ModelAgent("backup_worker", "mock", tags=("reasoning", "writing"), priority=1),
    ]
    client = _AgentDownClient(down_id)
    orchestrator = TaskOrchestrator(agents, client=client)
    # Mechanical failover contract: real-time judging is orthogonal here and
    # its extra provider call would pollute the scripted call ledger.
    orchestrator.policy = replace(orchestrator.policy, realtime_judge=False)
    return orchestrator, client


def test_failover_to_backup_agent_when_primary_fails() -> None:
    orchestrator, client = _two_worker_orchestrator(down_id="primary_worker")
    result = orchestrator.route_once([{"role": "user", "content": "route this"}])
    assert result["answer"] == "[backup_worker] answer"
    row = result["trace"][0]
    assert row["served_agent_id"] == "backup_worker"
    assert row["failover_from"] == "primary_worker"
    assert client.calls == ["primary_worker", "backup_worker"]  # tried primary first, then failed over


def test_structural_provider_response_fails_over_to_next_provider() -> None:
    agents = [
        ModelAgent("primary_worker", "mock", tags=("reasoning", "writing"), priority=5),
        ModelAgent("backup_worker", "mock", tags=("reasoning", "writing"), priority=1),
    ]

    class MalformedPrimaryClient(ModelClient):
        def __init__(self) -> None:
            super().__init__(retry_backoff=0.0)
            self.calls: list[str] = []

        def chat(self, agent: ModelAgent, messages: list, temperature: float = 0.2) -> str:  # type: ignore[override]
            self.calls.append(agent.id)
            if agent.id == "primary_worker":
                raise ProviderResponseError("provider primary_worker response did not contain assistant content")
            return "backup answer"

    client = MalformedPrimaryClient()
    orchestrator = TaskOrchestrator(agents, client=client)

    output, served_id, _usage = orchestrator._invoke(
        agents[0], [{"role": "user", "content": "route this"}], text="route this", role="worker"
    )

    assert output == "backup answer"
    assert served_id == "backup_worker"
    assert client.calls == ["primary_worker", "backup_worker"]


def test_exhausted_provider_transport_uses_failover_error_category() -> None:
    """Transport exhaustion cannot enter the orchestration tool-retry loop."""
    class TransportFailureClient(ModelClient):
        def __init__(self) -> None:
            super().__init__(max_retries=0, retry_backoff=0.0)
            self.calls: list[str] = []

        def _send(self, agent: ModelAgent, payload: dict, destination=None) -> str:  # type: ignore[override]
            self.calls.append(agent.id)
            raise RuntimeError("provider transport failed")

    client = TransportFailureClient()
    agent = ModelAgent(
        "primary_worker", "mock", base_url="https://provider.example/v1", tags=("reasoning",)
    )
    with pytest.raises(ProviderResponseError):
        client._send_with_retry(agent, {"model": agent.model})
    assert client.calls == ["primary_worker"]


def test_provider_retry_reuses_one_timeout_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    """Transport retries receive only the remainder of one provider-attempt budget."""
    now = [0.0]
    monkeypatch.setattr(orchestrator_module.time, "monotonic", lambda: now[0])

    class TimedFailureClient(ModelClient):
        def __init__(self) -> None:
            super().__init__(timeout=90, max_retries=1, retry_backoff=0.0)
            self.timeouts: list[float] = []

        def _send(self, agent, payload, destination=None, *, timeout=None):  # type: ignore[override]
            del agent, payload, destination
            timeout = self._local.provider_transport_timeout
            self.timeouts.append(timeout)
            now[0] += 60.0
            raise TimeoutError("provider timed out")

    client = TimedFailureClient()
    agent = ModelAgent("provider_worker", "provider-model", base_url="https://provider.example/v1")
    with pytest.raises(ProviderResponseError):
        client._send_with_retry(agent, {"model": agent.model})
    assert client.timeouts == [90.0, 30.0]


def test_structured_passthrough_retries_share_one_provider_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Structured raw-provider retries cannot restart the transport timeout."""
    now = [0.0]
    monkeypatch.setattr(orchestrator_module.time, "monotonic", lambda: now[0])

    class TimedRawFailureClient(ModelClient):
        def __init__(self) -> None:
            super().__init__(timeout=90, max_retries=2, retry_backoff=0.0)
            self.timeouts: list[float] = []

        def _send_raw(self, agent, endpoint, payload, destination=None, *, timeout=None):  # type: ignore[override]
            del agent, endpoint, payload, destination, timeout
            remaining = self._local.provider_transport_timeout
            self.timeouts.append(remaining)
            now[0] += min(60.0, remaining)
            raise TimeoutError("structured provider timed out")

    client = TimedRawFailureClient()
    agent = ModelAgent("provider_worker", "provider-model", base_url="https://provider.example/v1")
    with pytest.raises(RuntimeError, match="passthrough request failed"):
        client._send_raw_with_retry(
            agent,
            "chat/completions",
            {"model": agent.model, "response_format": {"type": "json_object"}},
        )
    assert client.timeouts == [90.0, 30.0]
    assert now[0] == 90.0


def test_request_deadline_allows_backup_only_the_remaining_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 180-second caller budget survives one 90-second provider exhaustion."""
    now = [0.0]
    monkeypatch.setattr(orchestrator_module.time, "monotonic", lambda: now[0])

    class DeadlineClient(ModelClient):
        def __init__(self) -> None:
            super().__init__(timeout=90, max_retries=0)
            self.calls: list[tuple[str, float]] = []

        def _validate_provider(self, agent):  # type: ignore[override]
            del agent
            return None

        def _send(self, agent, payload, destination=None, *, timeout=None):  # type: ignore[override]
            del payload, destination
            timeout = self._local.provider_transport_timeout
            self.calls.append((agent.id, timeout))
            if agent.id == "primary_worker":
                now[0] += timeout
                raise TimeoutError("primary exhausted its provider budget")
            self._local.usage = {"completion_tokens": 7}
            return "backup answer"

    agents = [
        ModelAgent("primary_worker", "provider-model", base_url="https://provider.example/v1", credential_key="", tags=("reasoning",), priority=5),
        ModelAgent("backup_worker", "provider-model", base_url="https://provider.example/v1", credential_key="", tags=("reasoning",), priority=1),
    ]
    client = DeadlineClient()
    orchestrator = TaskOrchestrator(agents, client=client)
    with client.request_settings(request_deadline_monotonic=180.0):
        output, served, usage = orchestrator._invoke(
            agents[0], [{"role": "user", "content": "route"}], text="route", role="worker"
        )
    assert output == "backup answer"
    assert served == "backup_worker"
    assert usage == {"completion_tokens": 7}
    assert client.calls == [("primary_worker", 90.0), ("backup_worker", 90.0)]


def test_all_provider_failures_end_at_shared_request_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Candidate failover cannot continue after the explicit caller deadline."""
    now = [0.0]
    monkeypatch.setattr(orchestrator_module.time, "monotonic", lambda: now[0])

    class AllTimedOut(ModelClient):
        def __init__(self) -> None:
            super().__init__(timeout=90, max_retries=0)

        def _validate_provider(self, agent):  # type: ignore[override]
            del agent
            return None

        def _send(self, agent, payload, destination=None, *, timeout=None):  # type: ignore[override]
            del agent, payload, destination
            timeout = self._local.provider_transport_timeout
            now[0] += timeout
            raise TimeoutError("provider timed out")

    agents = [
        ModelAgent("primary_worker", "provider-model", base_url="https://provider.example/v1", credential_key="", tags=("reasoning",), priority=5),
        ModelAgent("backup_worker", "provider-model", base_url="https://provider.example/v1", credential_key="", tags=("reasoning",), priority=1),
    ]
    client = AllTimedOut()
    orchestrator = TaskOrchestrator(agents, client=client)
    with client.request_settings(request_deadline_monotonic=180.0):
        with pytest.raises(RequestDeadlineExceeded, match="request deadline exceeded"):
            orchestrator._invoke(
                agents[0], [{"role": "user", "content": "route"}], text="route", role="worker"
            )
    assert now[0] == 180.0


def test_raw_passthrough_retries_end_at_shared_request_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [0.0]
    monkeypatch.setattr(orchestrator_module.time, "monotonic", lambda: now[0])

    class TimedOutRawClient(ModelClient):
        def __init__(self) -> None:
            super().__init__(timeout=90, max_retries=3, retry_backoff=10)
            self.calls = 0

        def _send_raw(self, agent, endpoint, payload, destination=None):  # type: ignore[override]
            del agent, endpoint, payload, destination
            self.calls += 1
            now[0] += self._local.provider_transport_timeout
            raise TimeoutError("provider timed out")

        def _validate_provider(self, agent):  # type: ignore[override]
            del agent
            return None

    client = TimedOutRawClient()
    agent = ModelAgent(
        "worker_agent", "provider-model", base_url="https://provider.example/v1", credential_key=""
    )
    with client.request_settings(request_deadline_monotonic=5.0):
        with pytest.raises(RequestDeadlineExceeded, match="request deadline exceeded"):
            client.proxy_send(agent, "responses", {})

    assert client.calls == 1
    assert now[0] == 5.0


def test_chat_retry_converts_exhausted_caller_budget_to_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [0.0]
    monkeypatch.setattr(orchestrator_module.time, "monotonic", lambda: now[0])

    class TimedOutChatClient(ModelClient):
        def __init__(self) -> None:
            super().__init__(timeout=90, max_retries=0)

        def _send(self, agent, payload, destination=None, *, timeout=None):  # type: ignore[override]
            del agent, payload, destination, timeout
            now[0] += self._local.provider_transport_timeout
            raise TimeoutError("provider timed out")

    client = TimedOutChatClient()
    agent = ModelAgent(
        "worker_agent", "provider-model", base_url="https://provider.example/v1", credential_key=""
    )
    with client.request_settings(request_deadline_monotonic=5.0):
        with pytest.raises(RequestDeadlineExceeded, match="request deadline exceeded"):
            client._send_with_retry(
                agent,
                {"model": agent.model},
                timeout=client.remaining_request_timeout(),
            )

    assert now[0] == 5.0


def test_expired_caller_deadline_is_not_a_group_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(orchestrator_module.time, "monotonic", lambda: 10.0)
    agent = ModelAgent(
        "worker_agent", "provider-model", group_name="provider_group", tags=("reasoning",)
    )
    client = ModelClient()
    orchestrator = TaskOrchestrator([agent], client=client)

    with client.request_settings(request_deadline_monotonic=9.0):
        with pytest.raises(RequestDeadlineExceeded):
            orchestrator._invoke(
                agent, [{"role": "user", "content": "route"}], text="route", role="worker"
            )

    assert orchestrator._group_router.member_observation_count(agent.id) == 0


def test_expired_passthrough_deadline_is_not_a_group_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(orchestrator_module.time, "monotonic", lambda: 10.0)

    class RemoteClient(ModelClient):
        def _validate_provider(self, agent):  # type: ignore[override]
            del agent
            return None

    agent = ModelAgent(
        "worker_agent",
        "provider-model",
        base_url="https://provider.example/v1",
        credential_key="",
        group_name="provider_group",
    )
    client = RemoteClient()
    orchestrator = TaskOrchestrator([agent], client=client)

    with client.request_settings(request_deadline_monotonic=9.0):
        with pytest.raises(RequestDeadlineExceeded):
            orchestrator.proxy_completion(
                {"model": agent.model, "input": "hello"}, endpoint="responses"
            )

    assert orchestrator._group_router.member_observation_count(agent.id) == 0


def test_all_agents_failing_raises_after_trying_every_candidate() -> None:
    agents = [
        ModelAgent("primary_worker", "mock", tags=("reasoning",)),
        ModelAgent("backup_worker", "mock", tags=("reasoning",)),
    ]

    class AllDown(ModelClient):
        def chat(self, agent: ModelAgent, messages: list, temperature: float = 0.2) -> str:  # type: ignore[override]
            raise RuntimeError("everything is down")

    orchestrator = TaskOrchestrator(agents, client=AllDown())
    raised = False
    try:
        orchestrator.route_once([{"role": "user", "content": "route this"}])
    except RuntimeError as exc:
        raised = True
        assert "candidate agents failed" in str(exc)
        assert "everything is down" not in str(exc)
        assert exc.__cause__ is None
    assert raised


def test_circuit_breaker_opens_then_skips_dead_agent() -> None:
    orchestrator, client = _two_worker_orchestrator(down_id="primary_worker")
    primary = orchestrator._agent("primary_worker")

    # Each invoke fails on primary then succeeds on backup; primary accrues failures.
    for _ in range(orchestrator.circuit_failure_threshold):
        output, served, _usage = orchestrator._invoke(
            primary, [{"role": "system", "content": "Role: worker"}], text="task", role="worker"
        )
        assert served == "backup_worker"

    assert orchestrator._circuit_open("primary_worker") is True
    # Once open, the dead agent is dropped from the candidate list entirely.
    candidates = orchestrator._failover_candidates(primary, "task", "worker")
    assert [a.id for a in candidates] == ["backup_worker"]


def test_circuit_breaker_resets_after_cooldown() -> None:
    orchestrator, _ = _two_worker_orchestrator(down_id="primary_worker")
    orchestrator.circuit_reset_seconds = 0.0  # cooldown elapses immediately
    for _ in range(orchestrator.circuit_failure_threshold):
        orchestrator._record_failure("primary_worker")
    # With a zero cooldown the breaker allows a probe again.
    assert orchestrator._circuit_open("primary_worker") is False


def test_success_clears_prior_failures() -> None:
    orchestrator, _ = _two_worker_orchestrator(down_id="primary_worker")
    orchestrator._record_failure("primary_worker")
    orchestrator._record_failure("primary_worker")
    orchestrator._record_success("primary_worker")
    assert orchestrator._circuit_open("primary_worker") is False
    assert "primary_worker" not in orchestrator._circuit


def test_conduct_defers_without_probing_unready_discovered_pool() -> None:
    """A large discovered pool is metadata, not permission to call providers."""

    class CountingClient(ModelClient):
        def __init__(self) -> None:
            super().__init__()
            self.chat_calls = 0

        def chat(self, agent, messages, **kwargs):  # type: ignore[override]
            del agent, messages, kwargs
            self.chat_calls += 1
            raise AssertionError("unprobed provider must not receive a completion")

    client = CountingClient()
    agents = [
        ModelAgent(
            f"discovered_{index}",
            f"provider/model-{index}",
            base_url="https://provider.example/v1",
            tags=("reasoning", "writing", "verification"),
        )
        for index in range(455)
    ]
    orchestrator = TaskOrchestrator(agents, client=client)

    with pytest.raises(NoViableAgentError):
        orchestrator.conduct([{"role": "user", "content": "structured task"}])

    assert client.chat_calls == 0


def test_conduct_attempts_only_ready_candidates_once_after_failures() -> None:
    """Two readiness-admitted candidates produce at most two failed calls."""

    class FailingClient(ModelClient):
        def __init__(self) -> None:
            super().__init__()
            self.called: list[str] = []

        def chat(self, agent, messages, **kwargs):  # type: ignore[override]
            del messages, kwargs
            self.called.append(agent.id)
            raise ProviderResponseError("sanitized provider failure")

    client = FailingClient()
    agents = [
        ModelAgent(
            f"ready_{index}",
            f"provider/ready-{index}",
            base_url="https://provider.example/v1",
            tags=("reasoning", "writing", "verification"),
            group_name="declared_group",
        )
        for index in range(2)
    ]
    orchestrator = TaskOrchestrator(agents, client=client)
    orchestrator._structured_readiness = {
        agent.id: {"status": "ready", "checked_at": orchestrator_module.time.monotonic()}
        for agent in agents
    }

    with pytest.raises(NoViableAgentError):
        orchestrator.conduct([{"role": "user", "content": "structured task"}])

    assert sorted(client.called) == sorted(agent.id for agent in agents)
    assert all(
        orchestrator._structured_readiness[agent.id]["status"] == "not_ready"
        for agent in agents
    )


def test_circuit_breaker_counts_concurrent_failures() -> None:
    orchestrator, _ = _two_worker_orchestrator(down_id="primary_worker")
    calls = orchestrator.circuit_failure_threshold * 4
    barrier = threading.Barrier(calls, timeout=2.0)

    def record_failure(_index: int) -> None:
        barrier.wait()
        orchestrator._record_failure("primary_worker")

    with ThreadPoolExecutor(max_workers=calls) as pool:
        list(pool.map(record_failure, range(calls)))

    assert orchestrator._circuit["primary_worker"]["failures"] == float(calls)
    assert orchestrator._circuit_open("primary_worker") is True


def test_mock_path_is_unchanged_no_failover_no_circuit_state() -> None:
    # Regression guard: the default mock path must behave exactly as before —
    # single attempt, no failover metadata, no circuit state recorded.
    orchestrator = TaskOrchestrator([ModelAgent("solo_worker", "mock", tags=("reasoning", "writing"))])
    result = orchestrator.route_once([{"role": "user", "content": "hello"}])
    assert result["mode"] == "route"
    assert "served_agent_id" not in result["trace"][0]
    assert "failover_from" not in result["trace"][0]
    assert orchestrator._circuit == {}


def test_batch_boundary_hides_raw_upload_error_text_and_cause() -> None:
    """Provider Batch API failures surface one package-owned error (CWE-209).

    Regression: ``_batch_run`` (upload, poll, download) propagated raw
    ``urllib`` errors carrying the provider URL and response body out of
    ``batch_chat``.
    """
    class RawBatchFailureClient(ModelClient):
        def _validate_provider(self, agent):  # type: ignore[override]
            return None  # skip URL/credential validation; only the boundary matters here

        def _batch_run(self, agent, requests, temperature, poll_interval, poll_timeout, destination=None):  # type: ignore[override]
            raise RuntimeError("provider-secret-batch-body")

    client = RawBatchFailureClient()
    agent = ModelAgent("batch_worker", "gpt", base_url="https://provider.example/v1")
    try:
        client.batch_chat(agent, {"task_0": [{"role": "user", "content": "ping"}]})
    except RuntimeError as error:
        assert "batch request failed" in str(error)
        assert "provider-secret-batch-body" not in str(error)
        assert error.__cause__ is None
    else:  # pragma: no cover
        raise AssertionError("a failed provider batch must raise a package-owned error")


def test_mock_batch_path_is_not_wrapped() -> None:
    """The mock batch path keeps its plain results — no boundary wrapping."""
    client = ModelClient()
    agent = ModelAgent("solo_worker", "mock")
    results = client.batch_chat(agent, {"task_0": [{"role": "user", "content": "hello"}]})
    assert set(results) == {"task_0"}
    assert results["task_0"]["content"]


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
    print("ok")
