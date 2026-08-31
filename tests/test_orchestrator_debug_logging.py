"""DEBUG/WARNING instrumentation on the retry, circuit-breaker, and ranking paths.

Mirrors tests/test_provider_reliability.py's style for driving `ModelClient`
and `TaskOrchestrator` directly. The key property under test throughout: a
credential/API-key-shaped string that flows through a path that emits a DEBUG
log must never appear verbatim in captured log output.
"""

from __future__ import annotations

import io
import logging
import sys
import urllib.error
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.orchestrator import ModelClient  # noqa: E402

_ORCHESTRATOR_LOGGER_NAME = "contextual_orchestrator.orchestrator"
_FAKE_SECRET = "sk-FAKEFAKEFAKEFAKEFAKE1234567890"  # noqa: S105 - obviously non-functional fixture


@contextmanager
def _captured_logs(level: int) -> Iterator[io.StringIO]:
    """Attach an isolated StringIO handler to the orchestrator logger only."""
    logger = logging.getLogger(_ORCHESTRATOR_LOGGER_NAME)
    previous_level = logger.level
    previous_propagate = logger.propagate
    buffer = io.StringIO()
    handler = logging.StreamHandler(buffer)
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
    try:
        yield buffer
    finally:
        logger.removeHandler(handler)
        handler.close()
        logger.setLevel(previous_level)
        logger.propagate = previous_propagate


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://provider.example/chat/completions", code, "err", None, None)


def test_send_with_retry_debug_logs_redact_secret_shaped_error_message() -> None:
    """THE key secret-leak test: a fake credential shape must never reach captured logs."""

    class LeakyClient(ModelClient):
        def __init__(self) -> None:
            super().__init__(max_retries=0)

        def _send(self, agent: ModelAgent, payload: dict, destination=None) -> str:  # type: ignore[override]
            raise RuntimeError(f"upstream rejected request: api_key={_FAKE_SECRET}")

    client = LeakyClient()
    agent = ModelAgent("worker_agent", "gpt", base_url="https://provider.example/v1")
    with _captured_logs(logging.DEBUG) as buffer:
        try:
            client._send_with_retry(agent, {"model": "gpt"})
        except RuntimeError:
            pass
        else:  # pragma: no cover
            raise AssertionError("a failed provider request must raise")
    output = buffer.getvalue()
    assert "[REDACTED]" in output
    assert _FAKE_SECRET not in output


def test_send_with_retry_debug_logs_report_agent_and_attempts_without_debug_by_default() -> None:
    class FlakyClient(ModelClient):
        def __init__(self) -> None:
            super().__init__(max_retries=2, retry_backoff=0.0)
            self.attempts = 0

        def _send(self, agent: ModelAgent, payload: dict, destination=None) -> str:  # type: ignore[override]
            self.attempts += 1
            if self.attempts < 2:
                raise _http_error(503)
            return "recovered"

    client = FlakyClient()
    agent = ModelAgent("worker_agent", "gpt", base_url="https://provider.example/v1")

    with _captured_logs(logging.WARNING) as buffer:
        assert client._send_with_retry(agent, {"model": "gpt"}) == "recovered"
    assert buffer.getvalue() == ""  # no DEBUG noise, and no failure at WARNING either

    client.attempts = 0
    with _captured_logs(logging.DEBUG) as buffer:
        assert client._send_with_retry(agent, {"model": "gpt"}) == "recovered"
    debug_output = buffer.getvalue()
    assert "provider_attempt agent_id=worker_agent" in debug_output
    assert "provider_attempt_failed agent_id=worker_agent" in debug_output
    assert "provider_backoff agent_id=worker_agent" in debug_output


def test_provider_exhausted_warning_fires_without_verbose() -> None:
    class AlwaysDownClient(ModelClient):
        def __init__(self) -> None:
            super().__init__(max_retries=1, retry_backoff=0.0)

        def _send(self, agent: ModelAgent, payload: dict, destination=None) -> str:  # type: ignore[override]
            raise _http_error(503)

    client = AlwaysDownClient()
    agent = ModelAgent("worker_agent", "gpt", base_url="https://provider.example/v1")
    with _captured_logs(logging.WARNING) as buffer:
        try:
            client._send_with_retry(agent, {"model": "gpt"})
        except Exception:
            pass
    output = buffer.getvalue()
    assert "provider_exhausted agent_id=worker_agent" in output
    assert "final_error_type=" in output


def test_provider_rejected_permanent_fires_instead_of_exhausted_on_immediate_non_transient_failure() -> None:
    """A non-transient first failure never claims a retry budget it never used.

    With `max_retries=2` (a real, non-zero budget) and a first attempt that
    fails with a non-transient error (401, not in TRANSIENT_HTTP_STATUS), the
    loop breaks immediately without ever spending a retry. `provider_exhausted`
    ("used its full retry budget") would misclassify this as an exhaustion
    event; a distinctly named event for an immediate terminal rejection is
    the accurate one.
    """

    class AlwaysUnauthorizedClient(ModelClient):
        def __init__(self) -> None:
            super().__init__(max_retries=2, retry_backoff=0.0)
            self.attempts = 0

        def _send(self, agent: ModelAgent, payload: dict, destination=None) -> str:  # type: ignore[override]
            self.attempts += 1
            raise _http_error(401)

    client = AlwaysUnauthorizedClient()
    agent = ModelAgent("worker_agent", "gpt", base_url="https://provider.example/v1")
    with _captured_logs(logging.WARNING) as buffer:
        try:
            client._send_with_retry(agent, {"model": "gpt"})
        except Exception:
            pass
    assert client.attempts == 1  # no retry budget was actually consumed
    output = buffer.getvalue()
    assert "provider_exhausted" not in output
    assert "provider_rejected_permanent agent_id=worker_agent" in output
    assert "final_error_type=" in output


def test_send_raw_with_retry_also_distinguishes_permanent_rejection_from_exhaustion() -> None:
    """`_send_raw_with_retry` duplicates `_send_with_retry`'s retry loop and must share the fix."""

    class AlwaysUnauthorizedRawClient(ModelClient):
        def __init__(self) -> None:
            super().__init__(max_retries=2, retry_backoff=0.0)
            self.attempts = 0

        def _send_raw(self, agent: ModelAgent, endpoint: str, payload: dict, destination=None) -> dict:  # type: ignore[override]
            self.attempts += 1
            raise _http_error(401)

    client = AlwaysUnauthorizedRawClient()
    agent = ModelAgent("worker_agent", "gpt", base_url="https://provider.example/v1")
    with _captured_logs(logging.WARNING) as buffer:
        try:
            client._send_raw_with_retry(agent, "chat/completions", {})
        except Exception:
            pass
    assert client.attempts == 1
    output = buffer.getvalue()
    assert "provider_exhausted" not in output
    assert "provider_rejected_permanent agent_id=worker_agent" in output


def test_zero_retry_limit_with_transient_error_logs_no_retry_budget_not_permanent() -> None:
    """`max_retries=0` means no retry budget ever existed, so nothing was "exhausted" --
    and, separately, a *transient* error under a zero budget must not be mislabeled
    "permanent" either: "no retry budget was configured" and "this error is
    non-retryable by nature" are two independent facts. Uses a transient error
    (503, would normally be retried) deliberately, paired with the
    non-transient counterpart below to cover all 4 (retries>0 vs =0) x
    (transient vs non-transient) combinations.
    """

    class ZeroRetryClient(ModelClient):
        def __init__(self) -> None:
            super().__init__(max_retries=0)
            self.attempts = 0

        def _send(self, agent: ModelAgent, payload: dict, destination=None) -> str:  # type: ignore[override]
            self.attempts += 1
            raise _http_error(503)  # transient -- would normally be retried

    client = ZeroRetryClient()
    agent = ModelAgent("worker_agent", "gpt", base_url="https://provider.example/v1")
    with _captured_logs(logging.WARNING) as buffer:
        try:
            client._send_with_retry(agent, {"model": "gpt"})
        except Exception:
            pass
    assert client.attempts == 1
    output = buffer.getvalue()
    assert "provider_exhausted" not in output
    assert "provider_rejected_permanent" not in output
    assert "provider_no_retry_budget agent_id=worker_agent" in output
    assert "transient=True" in output


def test_zero_retry_limit_with_non_transient_error_logs_no_retry_budget_too() -> None:
    """Same zero-budget event fires for a non-transient error too, with `transient=False`."""

    class ZeroRetryUnauthorizedClient(ModelClient):
        def __init__(self) -> None:
            super().__init__(max_retries=0)
            self.attempts = 0

        def _send(self, agent: ModelAgent, payload: dict, destination=None) -> str:  # type: ignore[override]
            self.attempts += 1
            raise _http_error(401)  # non-transient

    client = ZeroRetryUnauthorizedClient()
    agent = ModelAgent("worker_agent", "gpt", base_url="https://provider.example/v1")
    with _captured_logs(logging.WARNING) as buffer:
        try:
            client._send_with_retry(agent, {"model": "gpt"})
        except Exception:
            pass
    assert client.attempts == 1
    output = buffer.getvalue()
    assert "provider_exhausted" not in output
    assert "provider_rejected_permanent" not in output
    assert "provider_no_retry_budget agent_id=worker_agent" in output
    assert "transient=False" in output


def test_send_raw_with_retry_zero_retry_limit_with_transient_error_logs_no_retry_budget() -> None:
    """`_send_raw_with_retry` duplicates the retry loop and must share the zero-retry fix."""

    class ZeroRetryRawClient(ModelClient):
        def __init__(self) -> None:
            super().__init__(max_retries=0)
            self.attempts = 0

        def _send_raw(self, agent: ModelAgent, endpoint: str, payload: dict, destination=None) -> dict:  # type: ignore[override]
            self.attempts += 1
            raise _http_error(503)  # transient -- would normally be retried

    client = ZeroRetryRawClient()
    agent = ModelAgent("worker_agent", "gpt", base_url="https://provider.example/v1")
    with _captured_logs(logging.WARNING) as buffer:
        try:
            client._send_raw_with_retry(agent, "chat/completions", {})
        except Exception:
            pass
    assert client.attempts == 1
    output = buffer.getvalue()
    assert "provider_exhausted" not in output
    assert "provider_rejected_permanent" not in output
    assert "provider_no_retry_budget agent_id=worker_agent" in output
    assert "transient=True" in output


def test_send_raw_with_retry_zero_retry_limit_with_non_transient_error_logs_no_retry_budget() -> None:
    """`_send_raw_with_retry` counterpart of the non-transient zero-budget case."""

    class ZeroRetryRawUnauthorizedClient(ModelClient):
        def __init__(self) -> None:
            super().__init__(max_retries=0)
            self.attempts = 0

        def _send_raw(self, agent: ModelAgent, endpoint: str, payload: dict, destination=None) -> dict:  # type: ignore[override]
            self.attempts += 1
            raise _http_error(401)  # non-transient

    client = ZeroRetryRawUnauthorizedClient()
    agent = ModelAgent("worker_agent", "gpt", base_url="https://provider.example/v1")
    with _captured_logs(logging.WARNING) as buffer:
        try:
            client._send_raw_with_retry(agent, "chat/completions", {})
        except Exception:
            pass
    assert client.attempts == 1
    output = buffer.getvalue()
    assert "provider_exhausted" not in output
    assert "provider_rejected_permanent" not in output
    assert "provider_no_retry_budget agent_id=worker_agent" in output
    assert "transient=False" in output


def test_send_raw_with_retry_one_shot_call_does_not_log_no_retry_budget() -> None:
    """`proxy_send_once`'s intentional single-attempt call must not claim `no_retry_budget`.

    Regression: with a real, non-zero configured retry budget (`max_retries=2`),
    calling `_send_raw_with_retry(..., allow_transient_retries=False)` -- the
    exact policy `proxy_send_once` uses so an already-failing-over passthrough
    request cannot itself amplify load with a nested retry loop -- forces
    `retry_limit` to 0 for this one call. Before the fix, `_log_retry_outcome`
    could not tell that apart from an agent that genuinely has no retry budget
    configured at all, and always logged the misleading
    `provider_no_retry_budget` event. It must now log a distinctly named
    `provider_one_shot_call_failed` event instead.
    """

    class OneShotRawClient(ModelClient):
        def __init__(self) -> None:
            super().__init__(max_retries=2, retry_backoff=0.0)
            self.attempts = 0

        def _send_raw(self, agent: ModelAgent, endpoint: str, payload: dict, destination=None) -> dict:  # type: ignore[override]
            self.attempts += 1
            raise _http_error(503)  # transient -- would normally be retried

    client = OneShotRawClient()
    agent = ModelAgent("worker_agent", "gpt", base_url="https://provider.example/v1")
    with _captured_logs(logging.WARNING) as buffer:
        try:
            client._send_raw_with_retry(
                agent, "chat/completions", {}, allow_transient_retries=False
            )
        except Exception:
            pass
    assert client.attempts == 1  # forced to exactly one attempt despite max_retries=2
    output = buffer.getvalue()
    assert "provider_no_retry_budget" not in output
    assert "provider_exhausted" not in output
    assert "provider_rejected_permanent" not in output
    assert "provider_one_shot_call_failed agent_id=worker_agent" in output
    assert "attempts=1" in output
    assert "transient=True" in output


def test_send_raw_with_retry_one_shot_call_reports_transient_false_too() -> None:
    """The one-shot event carries the real `transient` classification, not a fixed value."""

    class OneShotRawUnauthorizedClient(ModelClient):
        def __init__(self) -> None:
            super().__init__(max_retries=2, retry_backoff=0.0)
            self.attempts = 0

        def _send_raw(self, agent: ModelAgent, endpoint: str, payload: dict, destination=None) -> dict:  # type: ignore[override]
            self.attempts += 1
            raise _http_error(401)  # non-transient

    client = OneShotRawUnauthorizedClient()
    agent = ModelAgent("worker_agent", "gpt", base_url="https://provider.example/v1")
    with _captured_logs(logging.WARNING) as buffer:
        try:
            client._send_raw_with_retry(
                agent, "chat/completions", {}, allow_transient_retries=False
            )
        except Exception:
            pass
    assert client.attempts == 1
    output = buffer.getvalue()
    assert "provider_no_retry_budget" not in output
    assert "provider_one_shot_call_failed agent_id=worker_agent" in output
    assert "transient=False" in output


def test_proxy_send_once_one_shot_failure_does_not_log_no_retry_budget() -> None:
    """End-to-end: `proxy_send_once` itself must not emit the misleading event."""

    class OneShotProxyClient(ModelClient):
        def __init__(self) -> None:
            super().__init__(max_retries=2, retry_backoff=0.0)

        def _send_raw(self, agent: ModelAgent, endpoint: str, payload: dict, destination=None) -> dict:  # type: ignore[override]
            raise _http_error(503)

    client = OneShotProxyClient()
    agent = ModelAgent("worker_agent", "gpt", base_url="https://provider.example/v1")
    with (
        patch.object(client, "_validate_provider", return_value=(2, ("203.0.113.10", 443))),
        _captured_logs(logging.WARNING) as buffer,
    ):
        try:
            client.proxy_send_once(agent, "chat/completions", {"model": "gpt"})
        except Exception:
            pass
    output = buffer.getvalue()
    assert "provider_no_retry_budget" not in output
    assert "provider_one_shot_call_failed agent_id=worker_agent" in output


def test_circuit_opened_emits_warning_without_debug() -> None:
    """The WARNING-tier edge-transition line fires by default; the per-increment DEBUG line does not."""
    orchestrator = TaskOrchestrator([ModelAgent("solo_agent", "mock-model")])
    orchestrator.circuit_failure_threshold = 2
    with _captured_logs(logging.WARNING) as buffer:
        orchestrator._record_failure("solo_agent")
        assert buffer.getvalue() == ""  # first failure: below threshold, no transition yet
        orchestrator._record_failure("solo_agent")
        output = buffer.getvalue()
    assert "circuit_opened agent_id=solo_agent" in output
    assert "circuit_failure" not in output  # DEBUG-tier line must not appear at WARNING


def test_circuit_failure_debug_log_fires_on_every_increment() -> None:
    orchestrator = TaskOrchestrator([ModelAgent("solo_agent", "mock-model")])
    orchestrator.circuit_failure_threshold = 5
    with _captured_logs(logging.DEBUG) as buffer:
        orchestrator._record_failure("solo_agent")
        orchestrator._record_failure("solo_agent")
        output = buffer.getvalue()
    assert output.count("circuit_failure agent_id=solo_agent") == 2


def test_circuit_cleared_only_logs_when_state_existed() -> None:
    orchestrator = TaskOrchestrator([ModelAgent("solo_agent", "mock-model")])
    orchestrator.circuit_failure_threshold = 5
    with _captured_logs(logging.DEBUG) as buffer:
        orchestrator._record_success("solo_agent")  # nothing to clear yet
        assert "circuit_cleared" not in buffer.getvalue()
        orchestrator._record_failure("solo_agent")
        orchestrator._record_success("solo_agent")  # now clears real state
        output = buffer.getvalue()
    assert "circuit_cleared agent_id=solo_agent" in output


def test_circuit_reset_debug_log_fires_on_cooldown_expiry() -> None:
    orchestrator = TaskOrchestrator([ModelAgent("solo_agent", "mock-model")])
    orchestrator.circuit_failure_threshold = 1
    orchestrator.circuit_reset_seconds = 0.0
    orchestrator._record_failure("solo_agent")
    with _captured_logs(logging.DEBUG) as buffer:
        assert orchestrator._circuit_open("solo_agent") is False
        output = buffer.getvalue()
    assert "circuit_reset agent_id=solo_agent" in output


def test_ranked_agents_debug_logs_include_agent_id_not_prompt_text() -> None:
    distinctive_prompt = "the quick zephyrblorp fox jumps xyzzy1234"
    orchestrator = TaskOrchestrator(
        [
            ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing")),
            ModelAgent("second_agent", "mock-second", tags=("reasoning", "writing")),
        ]
    )
    with _captured_logs(logging.DEBUG) as buffer:
        orchestrator._ranked_agents(distinctive_prompt, "worker")
        output = buffer.getvalue()
    assert "general_agent" in output or "second_agent" in output
    assert distinctive_prompt not in output


def test_select_agent_debug_log_reports_chosen_agent() -> None:
    orchestrator = TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )
    with _captured_logs(logging.DEBUG) as buffer:
        selected = orchestrator._select_agent("hello", "worker")
        output = buffer.getvalue()
    assert f"chosen_agent_id={selected.id}" in output
    assert f"chosen_model={selected.model}" in output


if __name__ == "__main__":  # pragma: no cover
    test_send_with_retry_debug_logs_redact_secret_shaped_error_message()
    test_send_with_retry_debug_logs_report_agent_and_attempts_without_debug_by_default()
    test_provider_exhausted_warning_fires_without_verbose()
    test_circuit_opened_emits_warning_without_debug()
    test_circuit_failure_debug_log_fires_on_every_increment()
    test_circuit_cleared_only_logs_when_state_existed()
    test_circuit_reset_debug_log_fires_on_cooldown_expiry()
    test_ranked_agents_debug_logs_include_agent_id_not_prompt_text()
    test_select_agent_debug_log_reports_chosen_agent()
    print("ok")
