"""Production TLS and bounded tool-retry policy contracts."""

from __future__ import annotations

import sys
from typing import Any

import pytest

from contextual_orchestrator import (
    MAX_TOOL_RETRY_ATTEMPTS,
    ModelAgent,
    TaskOrchestrator,
)
from contextual_orchestrator.__main__ import main as cli_main
from contextual_orchestrator.orchestrator import ModelClient
from contextual_orchestrator.tool_fallback import ToolExecutionError, ToolFailureKind


@pytest.mark.parametrize("value", [None, 0, 1, 0.0, "", [], {}])
def test_provider_tls_verification_requires_an_exact_boolean(value: object) -> None:
    """Reject false-like non-booleans before an unverified context can be selected."""
    with pytest.raises(TypeError, match="verify_tls must be a boolean"):
        ModelClient(verify_tls=value)  # type: ignore[arg-type]


def test_http_serve_rejects_the_development_tls_opt_out(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Keep the insecure provider path unavailable to the production HTTP server."""
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "contextual-orchestrator",
            "--serve",
            "--auth-token",
            "test-token",
            "--insecure-skip-tls-verify",
        ],
    )
    with pytest.raises(SystemExit) as raised:
        cli_main()
    assert raised.value.code == 2
    assert "cannot be used with --serve" in capsys.readouterr().err


def _agents() -> list[ModelAgent]:
    """Return a deterministic primary and backup pair for retry-policy tests."""
    return [
        ModelAgent(
            "primary_worker",
            "mock",
            tags=("reasoning", "writing"),
            priority=10,
        ),
        ModelAgent(
            "backup_worker",
            "mock",
            tags=("reasoning", "writing"),
            priority=1,
        ),
    ]


class _AlwaysTransientPrimary(ModelClient):
    """Fail every primary call safely and recover through the backup."""

    def __init__(self) -> None:
        super().__init__(max_retries=0)
        self.calls: list[str] = []

    def chat(
        self,
        agent: ModelAgent,
        messages: list[dict[str, Any]],
        temperature: float = 0.2,
    ) -> str:
        """Record calls and raise one explicitly idempotent tool timeout."""
        del messages, temperature
        self.calls.append(agent.id)
        if agent.id == "primary_worker":
            raise ToolExecutionError(
                "read timed out",
                tool_name="inspect_repository",
                kind=ToolFailureKind.TIMEOUT,
                idempotent=True,
            )
        return "backup recovered"


def test_tool_retry_attempts_rejects_values_above_the_shared_policy_cap() -> None:
    """Reject a configuration that could occupy one request indefinitely."""
    with pytest.raises(ValueError, match=rf"at most {MAX_TOOL_RETRY_ATTEMPTS}"):
        TaskOrchestrator(
            _agents(),
            tool_retry_attempts=MAX_TOOL_RETRY_ATTEMPTS + 1,
        )


def test_retry_loop_defends_the_cap_if_runtime_state_is_mutated() -> None:
    """Apply the shared cap again at execution time before agent failover."""
    client = _AlwaysTransientPrimary()
    orchestrator = TaskOrchestrator(
        _agents(),
        client=client,
        tool_retry_attempts=MAX_TOOL_RETRY_ATTEMPTS,
        tool_retry_backoff_seconds=0,
    )
    orchestrator.tool_retry_attempts = MAX_TOOL_RETRY_ATTEMPTS + 100

    result = orchestrator.route_once(
        [{"role": "user", "content": "inspect the repository"}]
    )

    assert result["answer"] == "backup recovered"
    assert client.calls == ["primary_worker"] * (
        MAX_TOOL_RETRY_ATTEMPTS + 1
    ) + ["backup_worker"]
