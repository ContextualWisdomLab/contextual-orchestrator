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

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.orchestrator import (  # noqa: E402
    TRANSIENT_HTTP_STATUS,
    ModelClient,
    ProviderResponseError,
    is_transient_error,
)
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
    return TaskOrchestrator(agents, client=client), client


def test_failover_to_backup_agent_when_primary_fails() -> None:
    orchestrator, client = _two_worker_orchestrator(down_id="primary_worker")
    result = orchestrator.route_once([{"role": "user", "content": "route this"}])
    assert result["answer"] == "[backup_worker] answer"
    row = result["trace"][0]
    assert row["served_agent_id"] == "backup_worker"
    assert row["failover_from"] == "primary_worker"
    assert client.calls == ["primary_worker", "backup_worker"]  # tried primary first, then failed over


def test_structural_provider_response_stops_before_tool_failover() -> None:
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
            return "backup must not be called"

    client = MalformedPrimaryClient()
    orchestrator = TaskOrchestrator(agents, client=client)

    try:
        orchestrator._invoke(
            agents[0], [{"role": "user", "content": "route this"}], text="route this", role="worker"
        )
    except ProviderResponseError as exc:
        assert "did not contain assistant content" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("a structurally invalid provider response must fail closed")

    assert client.calls == ["primary_worker"]
    assert orchestrator._circuit == {}


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


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
    print("ok")
