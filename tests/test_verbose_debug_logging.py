"""Verbose/DEBUG logging: enablement, bounded control-flow evidence, and secret safety.

Covers the CLI ``--verbose``/``CONTEXTUAL_ORCHESTRATOR_VERBOSE`` wiring in
``__main__.py`` plus the DEBUG-level ``.debug()`` call sites added to
``orchestrator.py`` and ``server.py``: dispatch route-vs-conduct choice,
route/conduct step transitions, provider request/retry attempts, invoke
failover/circuit-breaker decisions, and the HTTP request/response lifecycle.
Every log-content assertion in this file also proves the negative -- DEBUG
entries are absent unless DEBUG is enabled, and never carry a secret, an
Authorization header, or raw prompt/response text.
"""

from __future__ import annotations

import io
import json
import logging
import time
import urllib.error
from contextlib import contextmanager
from dataclasses import replace
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.__main__ import (  # noqa: E402
    VERBOSE_ENV_VAR,
    _configure_logging,
    _env_flag,
    main,
)
from contextual_orchestrator.credentials import (  # noqa: E402
    InMemoryCredentialBackend,
    set_backend,
)
from contextual_orchestrator.orchestrator import ModelClient  # noqa: E402
from contextual_orchestrator.server import build_server  # noqa: E402

FAKE_SECRET = "sk-live-should-never-appear-9f8e7d6c5b4a"  # noqa: S105 - fixture value, not a real key


@pytest.fixture
def restore_root_logger():
    """Snapshot and restore the root logger so ``_configure_logging`` never leaks between tests."""
    root = logging.getLogger()
    original_level = root.level
    original_handlers = root.handlers[:]
    try:
        yield
    finally:
        root.handlers[:] = original_handlers
        root.setLevel(original_level)


def _agents() -> list[ModelAgent]:
    return [
        ModelAgent("planner_agent", "mock-planner", tags=("planning", "reasoning")),
        ModelAgent("builder_agent", "mock-builder", tags=("coding", "implementation"), priority=1),
        ModelAgent("reviewer_agent", "mock-reviewer", tags=("verification", "security", "review"), priority=2),
    ]


def build() -> TaskOrchestrator:
    return TaskOrchestrator(_agents())


# -- CLI enablement --------------------------------------------------------


def test_env_flag_accepts_common_truthy_spellings_only(monkeypatch) -> None:
    """The env escape hatch parses a small explicit truthy vocabulary, fail-closed otherwise."""
    for value in ("1", "true", "True", "yes", "on"):
        monkeypatch.setenv(VERBOSE_ENV_VAR, value)
        assert _env_flag(VERBOSE_ENV_VAR) is True
    for value in ("", "0", "false", "no", "off", "maybe"):
        monkeypatch.setenv(VERBOSE_ENV_VAR, value)
        assert _env_flag(VERBOSE_ENV_VAR) is False
    monkeypatch.delenv(VERBOSE_ENV_VAR, raising=False)
    assert _env_flag(VERBOSE_ENV_VAR) is False


def test_configure_logging_is_a_noop_unless_verbose(restore_root_logger) -> None:
    """Default (non-verbose) startup never touches process-wide logging configuration."""
    root = logging.getLogger()
    handlers_before = root.handlers[:]
    level_before = root.level
    _configure_logging(False)
    assert root.handlers == handlers_before
    assert root.level == level_before


def test_configure_logging_enables_debug_with_bounded_format(restore_root_logger) -> None:
    """Verbose startup configures DEBUG level with a timestamp/level/logger-name format."""
    root = logging.getLogger()
    _configure_logging(True)
    assert root.level == logging.DEBUG
    assert root.handlers, "verbose logging must attach a handler"
    formatter = root.handlers[0].formatter
    assert formatter is not None
    assert "%(asctime)s" in formatter._fmt
    assert "%(levelname)s" in formatter._fmt
    assert "%(name)s" in formatter._fmt


def test_serve_cli_flag_enables_debug_logging(restore_root_logger) -> None:
    """``--verbose`` on the main --serve parser reaches ``_configure_logging`` early."""
    root = logging.getLogger()
    with (
        patch("contextual_orchestrator.__main__.load_agents", return_value=[]),
        patch("contextual_orchestrator.__main__.ModelClient"),
        patch("contextual_orchestrator.__main__.TaskOrchestrator"),
        patch("contextual_orchestrator.__main__.CostRoutingCoordinator"),
        patch("contextual_orchestrator.__main__.serve") as serve,
    ):
        main(["--serve", "--auth-token", "token", "--verbose"])
    assert serve.called
    assert root.level == logging.DEBUG


def test_serve_cli_omits_debug_by_default(restore_root_logger) -> None:
    """Without ``--verbose`` (or the env var), startup leaves logging unconfigured."""
    root = logging.getLogger()
    handlers_before = root.handlers[:]
    level_before = root.level
    with (
        patch("contextual_orchestrator.__main__.load_agents", return_value=[]),
        patch("contextual_orchestrator.__main__.ModelClient"),
        patch("contextual_orchestrator.__main__.TaskOrchestrator"),
        patch("contextual_orchestrator.__main__.CostRoutingCoordinator"),
        patch("contextual_orchestrator.__main__.serve") as serve,
    ):
        main(["--serve", "--auth-token", "token"])
    assert serve.called
    assert root.handlers == handlers_before
    assert root.level == level_before


def test_verbose_env_var_enables_debug_without_a_new_cli_flag(monkeypatch, restore_root_logger) -> None:
    """A deployed server can turn on DEBUG logging via env alone, no CLI edit required."""
    monkeypatch.setenv(VERBOSE_ENV_VAR, "true")
    root = logging.getLogger()
    with (
        patch("contextual_orchestrator.__main__.load_agents", return_value=[]),
        patch("contextual_orchestrator.__main__.ModelClient"),
        patch("contextual_orchestrator.__main__.TaskOrchestrator"),
        patch("contextual_orchestrator.__main__.CostRoutingCoordinator"),
        patch("contextual_orchestrator.__main__.serve"),
    ):
        main(["--serve", "--auth-token", "token"])
    assert root.level == logging.DEBUG


def test_discover_models_and_register_credential_accept_verbose_flag(restore_root_logger) -> None:
    """The bootstrap subcommands expose the same flag for CLI consistency."""
    root = logging.getLogger()
    with (
        patch("contextual_orchestrator.__main__.discover_all_models", return_value=([], [])),
        patch("contextual_orchestrator.__main__._bootstrap_discovery_sources", return_value=()),
    ):
        main(["discover-models", "--verbose"])
    assert root.level == logging.DEBUG


# -- orchestration control-flow: dispatch / route / conduct ----------------


def test_dispatch_debug_log_reports_route_vs_conduct_choice(caplog) -> None:
    """The route-vs-conduct triage decision is visible at DEBUG, silent otherwise."""
    orchestrator = build()
    orchestrator._triage_fn = lambda text: "architecture" in text

    with caplog.at_level("DEBUG"):
        fast = orchestrator.complete([{"role": "user", "content": "Write one sentence."}], mode="auto")
    assert fast["mode"] == "route"
    assert "dispatch.decision mode=auto model=contextual-orchestrator path=route" in caplog.text

    caplog.clear()
    with caplog.at_level("DEBUG"):
        deep = orchestrator.complete(
            [{"role": "user", "content": "Analyze the architecture and implement it."}],
            mode="auto",
        )
    assert deep["mode"] == "conduct"
    assert "dispatch.decision mode=auto model=contextual-orchestrator path=conduct" in caplog.text


def test_dispatch_debug_log_is_absent_without_debug_level(caplog) -> None:
    """The same call produces no dispatch evidence when DEBUG is not enabled (the default)."""
    orchestrator = build()
    orchestrator._triage_fn = lambda text: False
    orchestrator.complete([{"role": "user", "content": "Write one sentence."}], mode="auto")
    assert "dispatch.decision" not in caplog.text


def test_conduct_step_debug_logs_report_role_and_agent_without_prompt_leakage(caplog) -> None:
    """Conduct-path step transitions expose role/agent/access scope, never task text."""
    orchestrator = build()
    secret_task = f"Analyze, implement, and verify. Credential: {FAKE_SECRET}"

    with caplog.at_level("DEBUG"):
        result = orchestrator.conduct([{"role": "user", "content": secret_task}])

    assert result["trace"], "conduct must produce at least one step"
    assert "conduct.step_started step_id=0 role=thinker agent_id=" in caplog.text
    assert "conduct.step_completed step_id=0 role=thinker agent_id=" in caplog.text
    assert "served_id=" in caplog.text
    assert "failover=" in caplog.text
    # Bounded metadata only: the task text (and the secret embedded in it)
    # must never reach a log record.
    assert FAKE_SECRET not in caplog.text
    assert secret_task not in caplog.text
    for step in result["trace"]:
        assert step["output"] not in caplog.text


def test_route_attempt_debug_logs_report_candidate_and_outcome(caplog) -> None:
    """Route-path candidate attempts expose agent/model/latency/acceptance, not content."""
    orchestrator = build()
    secret_prompt = f"Write one sentence. Token: {FAKE_SECRET}"

    with caplog.at_level("DEBUG"):
        result = orchestrator.route_once([{"role": "user", "content": secret_prompt}])

    assert "route.attempt_started attempt=0 agent_id=" in caplog.text
    assert "route.attempt_completed attempt=0 agent_id=" in caplog.text
    assert "accepted=" in caplog.text
    assert FAKE_SECRET not in caplog.text
    assert secret_prompt not in caplog.text
    assert result["answer"] not in caplog.text


def test_route_and_conduct_debug_logs_absent_by_default(caplog) -> None:
    """Route and conduct debug markers never appear without an explicit DEBUG level."""
    orchestrator = build()
    orchestrator.route_once([{"role": "user", "content": "hello"}])
    orchestrator.conduct([{"role": "user", "content": "Analyze, implement, and verify."}])
    for marker in ("route.attempt_started", "route.attempt_completed", "conduct.step_started", "conduct.step_completed"):
        assert marker not in caplog.text


def test_invoke_reports_candidate_attempts_and_success(caplog) -> None:
    """_invoke's per-candidate attempt and success evidence names the serving agent."""
    orchestrator = build()
    with caplog.at_level("DEBUG"):
        output, served_id, _usage = orchestrator._invoke(
            orchestrator.agents[0],
            [{"role": "user", "content": "hello"}],
            text="hello",
            role="worker",
        )
    assert output
    assert f"invoke.candidate_attempt role=worker agent_id={orchestrator.agents[0].id} candidate_index=0" in caplog.text
    assert f"invoke.success agent_id={served_id} role=worker" in caplog.text


# -- invoke failover and circuit breaker ------------------------------------


class _ScriptedClient(ModelClient):
    """Return or raise scripted outcomes by agent id, bypassing real network I/O."""

    def __init__(self, scripts: dict[str, list[object]]) -> None:
        super().__init__(max_retries=0)
        self.scripts = {agent_id: list(outcomes) for agent_id, outcomes in scripts.items()}
        self.calls: list[str] = []

    def chat(self, agent: ModelAgent, messages: list, temperature: float = 0.2) -> str:  # type: ignore[override]
        del messages, temperature
        self.calls.append(agent.id)
        outcome = self.scripts[agent.id].pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return str(outcome)


def _failover_orchestrator(client: ModelClient) -> TaskOrchestrator:
    agents = [
        ModelAgent("primary_worker", "mock", tags=("reasoning", "writing"), priority=5),
        ModelAgent("backup_worker", "mock", tags=("reasoning", "writing"), priority=1),
    ]
    orchestrator = TaskOrchestrator(agents, client=client, tool_retry_attempts=0)
    orchestrator.policy = replace(orchestrator.policy, realtime_judge=False)
    return orchestrator


def test_invoke_failover_debug_log_reports_classification_and_next_candidate(caplog) -> None:
    """A tool-not-found failure logs its classification before failing over."""
    client = _ScriptedClient(
        {
            "primary_worker": [RuntimeError("Tool execute_command not found in agent strix")],
            "backup_worker": ["recovered"],
        }
    )
    orchestrator = _failover_orchestrator(client)

    with caplog.at_level("DEBUG"):
        result = orchestrator.route_once([{"role": "user", "content": "scan this repository"}])

    assert result["trace"][0]["served_agent_id"] == "backup_worker"
    assert (
        "invoke.failure_classified agent_id=primary_worker role=worker "
        "kind=ToolFailureKind.TOOL_NOT_FOUND action=ToolFallbackAction.FAILOVER_AGENT"
        in caplog.text
    )
    assert "invoke.candidate_attempt role=worker agent_id=backup_worker candidate_index=1" in caplog.text
    assert "invoke.success agent_id=backup_worker" in caplog.text


def test_circuit_breaker_debug_logs_report_open_half_open_and_closed(monkeypatch, caplog) -> None:
    """Circuit state transitions are visible at DEBUG: opened, half-open, closed."""
    orchestrator = build()
    agent_id = "planner_agent"

    with caplog.at_level("DEBUG"):
        for _ in range(orchestrator.circuit_failure_threshold):
            orchestrator._record_failure(agent_id)
        assert orchestrator._circuit_open(agent_id) is True
        assert f"circuit.opened agent_id={agent_id} failures={orchestrator.circuit_failure_threshold}" in caplog.text

        # Simulate the reset window elapsing so the next probe resets to half-open.
        orchestrator._circuit[agent_id]["opened_at"] = (
            time.monotonic() - orchestrator.circuit_reset_seconds - 1.0
        )
        assert orchestrator._circuit_open(agent_id) is False
        assert f"circuit.half_open agent_id={agent_id}" in caplog.text

        orchestrator._record_failure(agent_id)  # re-populate so close is observable
        orchestrator._record_success(agent_id)
        assert f"circuit.closed agent_id={agent_id}" in caplog.text


def test_circuit_breaker_close_on_never_failing_agent_logs_nothing(caplog) -> None:
    """Recording success for an agent with no tracked failures is not a state transition."""
    orchestrator = build()
    with caplog.at_level("DEBUG"):
        orchestrator._record_success("planner_agent")
    assert "circuit.closed" not in caplog.text


# -- provider transport: request, retry, backoff ----------------------------


def test_provider_request_and_retry_debug_logs_are_bounded(monkeypatch, caplog) -> None:
    """Provider attempt/retry logs report agent/model/host and error TYPE, never secrets."""
    backend = InMemoryCredentialBackend()
    backend.set("OPENAI_API_KEY", FAKE_SECRET)
    set_backend(backend)
    try:
        client = ModelClient(max_retries=1)
        client._sleep = lambda _seconds: None  # skip real backoff sleep in tests
        agent = ModelAgent(
            "secret_agent",
            "model-y",
            base_url="https://provider.example/v1",
            credential_key="OPENAI_API_KEY",
            provider_name="openai",
        )
        captured_headers: dict[str, str] = {}
        attempts = {"count": 0}

        @contextmanager
        def fake_open(request, destination=None, timeout=None):  # noqa: ARG001
            attempts["count"] += 1
            captured_headers.update(dict(request.header_items()))
            if attempts["count"] == 1:
                raise urllib.error.HTTPError(
                    request.full_url, 503, "unavailable", None, io.BytesIO(b"{}")
                )
            yield io.BytesIO(
                json.dumps(
                    {
                        "model": "model-y",
                        "choices": [{"message": {"content": f"contains {FAKE_SECRET}"}}],
                    }
                ).encode("utf-8")
            )

        monkeypatch.setattr(client, "_validate_provider", lambda unused: None)
        monkeypatch.setattr(client, "_open_provider", fake_open)

        with caplog.at_level("DEBUG"):
            output = client.chat(agent, [{"role": "user", "content": f"my key is {FAKE_SECRET}"}])

        assert output == f"contains {FAKE_SECRET}"
        assert attempts["count"] == 2
        # Sanity: the secret really was sent to the (fake) provider.
        assert any(FAKE_SECRET in value for value in captured_headers.values())

        assert "provider.attempt agent_id=secret_agent model=model-y attempt=0 retry_limit=1" in caplog.text
        assert "provider.retry_scheduled agent_id=secret_agent attempt=0" in caplog.text
        assert "provider.attempt agent_id=secret_agent model=model-y attempt=1 retry_limit=1" in caplog.text
        assert "provider.request agent_id=secret_agent model=model-y provider=openai host=provider.example" in caplog.text

        # Never the credential, never the prompt, never the response content.
        assert FAKE_SECRET not in caplog.text
        assert "my key is" not in caplog.text
        assert "contains" not in caplog.text
        assert "authorization" not in caplog.text.lower()
    finally:
        set_backend(None)


def test_provider_retry_exhaustion_debug_log_reports_error_type_only(monkeypatch, caplog) -> None:
    """A non-retryable failure logs attempt_exhausted with the exception class, not its text."""
    client = ModelClient(max_retries=1)
    client._sleep = lambda _seconds: None
    agent = ModelAgent(
        "failing_agent",
        "model-y",
        base_url="https://provider.example/v1",
        credential_key="",
    )

    @contextmanager
    def always_fail(request, destination=None, timeout=None):  # noqa: ARG001
        raise urllib.error.HTTPError(
            request.full_url, 401, f"unauthorized secret={FAKE_SECRET}", None, io.BytesIO(b"{}")
        )
        yield  # pragma: no cover - unreachable, keeps this a generator

    monkeypatch.setattr(client, "_validate_provider", lambda unused: None)
    monkeypatch.setattr(client, "_open_provider", always_fail)

    with caplog.at_level("DEBUG"), pytest.raises(Exception):
        client.chat(agent, [{"role": "user", "content": "hello"}])

    assert "provider.attempt_exhausted agent_id=failing_agent attempt=0" in caplog.text
    assert "error_type=HTTPError" in caplog.text
    assert FAKE_SECRET not in caplog.text
    assert "provider.retry_scheduled" not in caplog.text


def test_provider_debug_logs_absent_without_debug_level(monkeypatch, caplog) -> None:
    """Provider request logging stays silent at the default level."""
    client = ModelClient()
    agent = ModelAgent(
        "quiet_agent",
        "model-z",
        base_url="https://provider.example/v1",
        credential_key="",
    )

    @contextmanager
    def fake_open(request, destination=None, timeout=None):  # noqa: ARG001
        yield io.BytesIO(
            json.dumps({"model": "model-z", "choices": [{"message": {"content": "ok"}}]}).encode("utf-8")
        )

    monkeypatch.setattr(client, "_validate_provider", lambda unused: None)
    monkeypatch.setattr(client, "_open_provider", fake_open)

    client.chat(agent, [{"role": "user", "content": "hello"}])
    assert "provider.request" not in caplog.text
    assert "provider.attempt" not in caplog.text


# -- HTTP request/response lifecycle (server.py) -----------------------------


def test_http_request_lifecycle_debug_logs_report_bounded_metadata(monkeypatch, caplog) -> None:
    """Request-start/response-sent DEBUG entries report method/path/status/latency only."""
    server = build_server(SimpleNamespace(agents=[], candidates=[]), port=0)
    handler = server.RequestHandlerClass.__new__(server.RequestHandlerClass)

    def fake_super_parse_request(self) -> bool:
        self.command = "POST"
        self.path = "/v1/chat/completions?authorization=leaked-secret-token"
        return True

    monkeypatch.setattr(BaseHTTPRequestHandler, "parse_request", fake_super_parse_request)

    try:
        with caplog.at_level("DEBUG"):
            assert handler.parse_request() is True
            handler.log_request(200)

        assert "http_request_received method=POST path=/v1/chat/completions" in caplog.text
        assert "http_response_sent method=POST path=/v1/chat/completions status=200 latency_ms=" in caplog.text
        assert "leaked-secret-token" not in caplog.text
    finally:
        server.server_close()


def test_http_request_lifecycle_debug_logs_absent_by_default(monkeypatch, caplog) -> None:
    """The same request/response lifecycle stays silent without DEBUG enabled."""
    server = build_server(SimpleNamespace(agents=[], candidates=[]), port=0)
    handler = server.RequestHandlerClass.__new__(server.RequestHandlerClass)

    def fake_super_parse_request(self) -> bool:
        self.command = "GET"
        self.path = "/healthz"
        return True

    monkeypatch.setattr(BaseHTTPRequestHandler, "parse_request", fake_super_parse_request)

    try:
        assert handler.parse_request() is True
        handler.log_request(200)
        assert "http_request_received" not in caplog.text
        assert "http_response_sent" not in caplog.text
    finally:
        server.server_close()

