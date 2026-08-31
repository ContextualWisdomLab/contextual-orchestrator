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
import re
import socket
import threading
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


#: Loggers _configure_logging may mutate: the root logger's handlers/format,
#: plus every individually audited logger it may raise to DEBUG (see
#: __main__._VERBOSE_LOGGER_NAMES) and the one deliberately UNAUDITED sibling
#: logger (openrouter_uptime) these tests prove stays untouched -- restoring
#: it too costs nothing and guards against a future regression there leaking
#: across tests the same way.
_LOGGERS_UNDER_TEST = (
    "",  # root
    "contextual_orchestrator.orchestrator",
    "contextual_orchestrator.server",
    "contextual_orchestrator.model_discovery",
    "contextual_orchestrator.openrouter_uptime",
)


@pytest.fixture
def restore_root_logger():
    """Snapshot and restore every logger ``_configure_logging`` may touch.

    Guards against ``_configure_logging(True)`` leaking a raised level (or,
    for root, a new handler/formatter) into unrelated tests later in the same
    process -- root's own handlers/level, plus the ``.level`` of each
    individually named logger it may set to DEBUG.
    """
    snapshots = [
        (name, logging.getLogger(name).level, logging.getLogger(name).handlers[:])
        for name in _LOGGERS_UNDER_TEST
    ]
    try:
        yield
    finally:
        for name, level, handlers in snapshots:
            logger = logging.getLogger(name)
            logger.setLevel(level)
            logger.handlers[:] = handlers


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


def test_configure_logging_attaches_a_bounded_format_handler_to_each_leaf_logger(
    restore_root_logger,
) -> None:
    """Verbose startup attaches its own formatted handler directly to each audited logger.

    Root's own LEVEL and handlers are left completely untouched -- see
    ``_VERBOSE_LOGGER_NAMES``'s docstring in ``__main__.py``: raising the
    ROOT (or a whole-package) logger's level would raise every child
    logger's EFFECTIVE level through inheritance, including loggers this
    change never audited. Attaching straight to each named leaf logger
    (rather than installing anything on root) guarantees delivery when
    nothing already covers it -- see
    ``test_configure_logging_still_emits_through_a_stricter_existing_root_handler``
    for the concrete case this design choice defends against, and
    ``test_configure_logging_skips_its_own_handler_when_a_permissive_host_handler_exists``
    for the mirror-image case (a handler is skipped, not duplicated, when
    propagation already delivers).

    Clears ``root.handlers`` first to simulate a genuinely bare process:
    pytest's own logging-capture machinery attaches its own root handlers
    (level ``NOTSET``, i.e. already permissive) regardless of anything this
    test sets up, which would otherwise make ``_logger_already_delivers_debug``
    correctly, but unhelpfully for this test, conclude propagation already
    covers it.
    """
    root = logging.getLogger()
    root.handlers.clear()
    level_before, handlers_before = root.level, root.handlers[:]
    _configure_logging(True)
    assert root.level == level_before
    assert root.handlers == handlers_before, "root's own handlers must be untouched"
    for logger_name in (
        "contextual_orchestrator.orchestrator",
        "contextual_orchestrator.server",
        "contextual_orchestrator.model_discovery",
    ):
        logger = logging.getLogger(logger_name)
        assert logger.level == logging.DEBUG, logger_name
        own_handlers = [h for h in logger.handlers if h.name == "contextual_orchestrator.verbose"]
        assert len(own_handlers) == 1, logger_name
        formatter = own_handlers[0].formatter
        assert formatter is not None
        assert "%(asctime)s" in formatter._fmt
        assert "%(levelname)s" in formatter._fmt
        assert "%(name)s" in formatter._fmt


def test_configure_logging_still_emits_through_a_stricter_existing_root_handler(
    restore_root_logger,
) -> None:
    """SEC/availability regression: a hosted process's own handler must not silence verbose mode.

    Devin's fifth review round caught this real follow-up to the
    force=True fix: once verbose mode correctly stops touching root's
    handlers, a *pre-existing* root handler with its own threshold above
    DEBUG (very plausible for anything hosting this process with its own
    logging setup, e.g. ``setLevel(logging.INFO)``) filters independently
    of the logger-level check -- a DEBUG record from an audited logger
    would propagate to it and be silently dropped there, producing zero
    verbose output with no error. Reproduced directly before this fix: a
    record from ``contextual_orchestrator.orchestrator`` never reached an
    INFO-level root handler even though the logger itself was raised to
    DEBUG, because no handler was ever attached directly to that logger.

    Note: this intentionally replaces ``.emit`` on the *specific handler
    instance* ``_configure_logging`` attaches (found by name), never on the
    ``logging.StreamHandler`` class globally -- an earlier draft of this
    test patched the class itself and, without noticing, also intercepted
    pytest's own internal handler construction (its live-log/caplog
    reporting), which made the assertion pass even against the pre-fix code
    for the wrong reason.

    Also clears ``root.handlers`` before adding the INFO-level host handler:
    pytest's own root handlers (level ``NOTSET``) would otherwise also sit
    in the propagation chain and make ``_logger_already_delivers_debug``
    correctly see a permissive handler -- just not the one this test means
    to isolate.
    """
    root = logging.getLogger()
    root.handlers.clear()
    hosted_records: list[logging.LogRecord] = []
    hosted_handler = logging.Handler()
    hosted_handler.setLevel(logging.INFO)
    hosted_handler.emit = hosted_records.append  # type: ignore[method-assign]
    close_calls: list[bool] = []
    hosted_handler.close = lambda: close_calls.append(True)  # type: ignore[method-assign]
    root.addHandler(hosted_handler)

    _configure_logging(True)

    orchestrator_logger = logging.getLogger("contextual_orchestrator.orchestrator")
    own_handler = next(
        (h for h in orchestrator_logger.handlers if h.name == "contextual_orchestrator.verbose"),
        None,
    )
    assert own_handler is not None, "verbose mode must attach its own handler to the leaf logger"
    delivered: list[logging.LogRecord] = []
    own_handler.emit = delivered.append  # type: ignore[method-assign]

    orchestrator_logger.debug(
        "dispatch.decision mode=auto model=contextual-orchestrator path=route"
    )

    assert any(
        record.getMessage() == "dispatch.decision mode=auto model=contextual-orchestrator path=route"
        for record in delivered
    ), "verbose mode's own dedicated handler must receive the record"
    assert hosted_records == [], "the hosted INFO-level handler correctly filters DEBUG on its own"
    assert hosted_handler in root.handlers, "the hosted handler must remain attached"
    assert close_calls == [], "the hosted handler must never be closed"
    for logger_name in (
        "contextual_orchestrator.orchestrator",
        "contextual_orchestrator.server",
        "contextual_orchestrator.model_discovery",
    ):
        assert logging.getLogger(logger_name).level == logging.DEBUG, logger_name


def test_configure_logging_skips_its_own_handler_when_a_permissive_host_handler_exists(
    restore_root_logger,
) -> None:
    """SEC/availability regression: a permissive host handler must not receive duplicate records.

    Devin's sixth review round caught this mirror-image case to round 5's
    fix: once the dedicated per-logger handler guarantees delivery past a
    STRICT host handler (see the test above), a host whose own handler is
    already PERMISSIVE (no level set, or set at/below DEBUG -- extremely
    common, since a fresh ``logging.Handler()`` and ``StreamHandler()``
    both default to ``NOTSET``) would otherwise see every matching record
    twice: once via propagation to its own handler, once via the new
    dedicated one. ``_logger_already_delivers_debug`` closes that by
    skipping the dedicated handler precisely when propagation to an
    existing handler already covers DEBUG.

    Clears ``root.handlers`` first for the same reason as the two tests
    above: pytest's own root handlers are themselves already permissive and
    would otherwise make this pass for the wrong reason regardless of the
    handler this test explicitly sets up.
    """
    root = logging.getLogger()
    root.handlers.clear()
    delivered: list[logging.LogRecord] = []
    permissive_handler = logging.Handler()  # level defaults to NOTSET
    permissive_handler.emit = delivered.append  # type: ignore[method-assign]
    root.addHandler(permissive_handler)

    _configure_logging(True)

    orchestrator_logger = logging.getLogger("contextual_orchestrator.orchestrator")
    own_handlers = [
        h for h in orchestrator_logger.handlers if h.name == "contextual_orchestrator.verbose"
    ]
    assert own_handlers == [], (
        "verbose mode must not attach a redundant handler when propagation "
        "to an existing permissive handler already delivers DEBUG"
    )

    orchestrator_logger.debug(
        "dispatch.decision mode=auto model=contextual-orchestrator path=route"
    )

    matching = [
        record
        for record in delivered
        if record.getMessage()
        == "dispatch.decision mode=auto model=contextual-orchestrator path=route"
    ]
    assert len(matching) == 1, f"record must be delivered exactly once via propagation, got {len(matching)}"
    assert orchestrator_logger.level == logging.DEBUG


def test_configure_logging_never_discards_an_existing_root_handler(
    restore_root_logger,
) -> None:
    """SEC/availability regression: verbose mode must never destroy existing log delivery.

    Devin's fourth review round caught this: an earlier version called
    ``logging.basicConfig(..., force=True)``, which unconditionally closes
    and removes every existing root handler before installing its own --
    silently discarding whatever a hosting runtime (a structured/JSON
    logging handler, a log shipper) or a test harness had already
    configured, replacing it with a plain stderr handler the moment
    ``--verbose`` was turned on. This preconfigures a custom root handler
    (simulating that already-configured delivery path), enables verbose
    mode, and asserts the custom handler is still attached, was never
    closed, and still receives an audited logger's DEBUG record.
    """
    root = logging.getLogger()
    custom_handler = logging.Handler()
    records: list[logging.LogRecord] = []
    custom_handler.emit = records.append  # type: ignore[method-assign]
    close_calls: list[bool] = []
    custom_handler.close = lambda: close_calls.append(True)  # type: ignore[method-assign]
    root.addHandler(custom_handler)

    _configure_logging(True)

    assert custom_handler in root.handlers, "verbose mode discarded an existing root handler"
    assert close_calls == [], "verbose mode must never close an existing root handler"

    logging.getLogger("contextual_orchestrator.orchestrator").debug("probe record")
    assert any(record.getMessage() == "probe record" for record in records), (
        "the preexisting handler must still receive records after verbose mode is enabled"
    )


def test_configure_logging_never_raises_openrouter_uptime_or_root(restore_root_logger) -> None:
    """SEC regression: verbose mode must not raise the root logger or an unaudited sibling.

    Devin's review confirmed: setting the ROOT logger's level (the original
    implementation) makes EVERY ``.debug()`` call site process-wide reachable,
    including ``openrouter_uptime.py``'s pre-existing
    ``logger.debug("...: %s", exc)`` -- which logs a raw upstream exception,
    not a classified/bounded value. Enabling verbose mode for
    route/conduct/provider/discovery visibility must not also newly expose
    that unrelated, unaudited call site.
    """
    _configure_logging(True)
    root = logging.getLogger()
    assert root.level != logging.DEBUG
    assert not logging.getLogger("contextual_orchestrator.openrouter_uptime").isEnabledFor(
        logging.DEBUG
    )


def test_verbose_mode_keeps_openrouter_uptime_failures_silent(
    monkeypatch, caplog, restore_root_logger
) -> None:
    """Concrete case: an OpenRouter uptime fetch failure stays silent even with verbose on.

    This is the exact call site (``openrouter_uptime.py``'s
    ``_fetch_uptime``) Devin's review named. It logs ``str(exc)`` directly at
    DEBUG and was never rewritten to stop doing that, so verbose mode must
    never raise ITS logger's level -- only the three audited-safe loggers.

    Deliberately does NOT wrap the call in ``caplog.at_level("DEBUG")``:
    that targets the ROOT logger by default, which would itself raise
    ``openrouter_uptime``'s inherited effective level to DEBUG regardless of
    what ``_configure_logging`` did -- an artificial condition production
    code never creates (root's level is never touched; see
    ``_VERBOSE_LOGGER_NAMES``). The realistic check is whether
    ``_configure_logging(True)`` alone -- which is what a real ``--verbose``
    run does -- lets this record through.
    """
    import contextual_orchestrator.openrouter_uptime as openrouter_uptime_module
    from contextual_orchestrator.model_group import ModelGroupRouter

    _configure_logging(True)
    secret_reason = f"upstream refused credential {FAKE_SECRET}"

    def fake_urlopen(request, timeout=None):  # noqa: ARG001
        raise urllib.error.URLError(secret_reason)

    monkeypatch.setattr(openrouter_uptime_module.urllib.request, "urlopen", fake_urlopen)
    collector = openrouter_uptime_module.OpenRouterUptimeCollector(
        [], ModelGroupRouter(), ModelGroupRouter()
    )

    result = collector._fetch_uptime("openrouter/some-model")

    assert result is None
    assert "Failed to fetch OpenRouter uptime" not in caplog.text
    assert secret_reason not in caplog.text
    assert FAKE_SECRET not in caplog.text


def test_serve_cli_flag_enables_debug_logging(restore_root_logger) -> None:
    """``--verbose`` on the main --serve parser reaches ``_configure_logging`` early."""
    with (
        patch("contextual_orchestrator.__main__.load_agents", return_value=[]),
        patch("contextual_orchestrator.__main__.ModelClient"),
        patch("contextual_orchestrator.__main__.TaskOrchestrator"),
        patch("contextual_orchestrator.__main__.CostRoutingCoordinator"),
        patch("contextual_orchestrator.__main__.serve") as serve,
    ):
        main(["--serve", "--auth-token", "token", "--verbose"])
    assert serve.called
    assert logging.getLogger("contextual_orchestrator.orchestrator").level == logging.DEBUG
    assert logging.getLogger("contextual_orchestrator.server").level == logging.DEBUG


def test_serve_cli_omits_debug_by_default(restore_root_logger) -> None:
    """Without ``--verbose`` (or the env var), startup leaves logging unconfigured."""
    root = logging.getLogger()
    handlers_before = root.handlers[:]
    level_before = root.level
    orchestrator_level_before = logging.getLogger("contextual_orchestrator.orchestrator").level
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
    assert (
        logging.getLogger("contextual_orchestrator.orchestrator").level
        == orchestrator_level_before
    )


def test_verbose_env_var_enables_debug_without_a_new_cli_flag(monkeypatch, restore_root_logger) -> None:
    """A deployed server can turn on DEBUG logging via env alone, no CLI edit required."""
    monkeypatch.setenv(VERBOSE_ENV_VAR, "true")
    with (
        patch("contextual_orchestrator.__main__.load_agents", return_value=[]),
        patch("contextual_orchestrator.__main__.ModelClient"),
        patch("contextual_orchestrator.__main__.TaskOrchestrator"),
        patch("contextual_orchestrator.__main__.CostRoutingCoordinator"),
        patch("contextual_orchestrator.__main__.serve"),
    ):
        main(["--serve", "--auth-token", "token"])
    assert logging.getLogger("contextual_orchestrator.orchestrator").level == logging.DEBUG


def test_discover_models_and_register_credential_accept_verbose_flag(
    monkeypatch, restore_root_logger
) -> None:
    """The bootstrap subcommands expose the same flag for CLI consistency.

    CodeRabbit review: the docstring and name claimed both subcommands were
    exercised, but the body only ever called ``discover-models`` -- the
    ``register-credential`` path was untested. Both are covered now.
    """
    with (
        patch("contextual_orchestrator.__main__.discover_all_models", return_value=([], [])),
        patch("contextual_orchestrator.__main__._bootstrap_discovery_sources", return_value=()),
    ):
        main(["discover-models", "--verbose"])
    assert logging.getLogger("contextual_orchestrator.model_discovery").level == logging.DEBUG

    monkeypatch.setenv("TEST_KEY_VALUE", "fixture-secret-value")  # noqa: S105 - fixture value, not a real key
    with patch("contextual_orchestrator.__main__.register_credential") as register_credential_mock:
        main(
            [
                "register-credential",
                "--name",
                "TEST_KEY",
                "--from-env",
                "TEST_KEY_VALUE",
                "--verbose",
            ]
        )
    register_credential_mock.assert_called_once_with("TEST_KEY", "fixture-secret-value")
    assert logging.getLogger("contextual_orchestrator.orchestrator").level == logging.DEBUG


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


# -- streaming route control-flow --------------------------------------------
#
# Devin review: stream_route/ModelClient.stream_chat/_stream_send are a
# structurally separate path from _dispatch/route_once/_invoke/
# _send_with_retry -- by design, per stream_route's own docstring ("no
# cross-agent failover here -- bytes already sent can't be recalled"), so
# every non-streaming routing/provider DEBUG log above stayed silent for a
# streamed request. These mirror the correct, simpler shape for streaming
# (one selection log, one outcome log, the same provider.request boundary
# event) rather than the retry/failover-aware non-streaming shape, which
# would misrepresent what streaming actually does.
#
# server.py's Chat Completions and Responses SSE handlers both call this
# exact same TaskOrchestrator.stream_route method with no endpoint-specific
# branching in it (see the two `orchestrator.stream_route(...)` call sites in
# server.py), so testing it once here covers both HTTP surfaces.


def test_stream_route_debug_logs_report_agent_selection_and_completion(caplog) -> None:
    """stream_route logs the selected agent, then the completed outcome."""
    orchestrator = build()
    with caplog.at_level("DEBUG"):
        parts = list(
            orchestrator.stream_route([{"role": "user", "content": "Write one sentence."}])
        )
    assert parts
    assert "stream.route_started agent_id=" in caplog.text
    assert "stream.route_completed agent_id=" in caplog.text
    assert "latency_ms=" in caplog.text


def test_stream_route_debug_log_reports_failure_before_reraising(monkeypatch, caplog) -> None:
    """A mid-stream provider failure logs its classification before propagating.

    Streaming cannot fail over (bytes already yielded can't be recalled), so
    unlike invoke.failure_classified this only reports the exception class
    name -- never str(exc), matching this file's error_type=%s convention
    for provider failures throughout.
    """
    orchestrator = build()

    def _broken_stream(agent, messages, **kwargs):  # noqa: ARG001
        raise RuntimeError("synthetic mid-stream failure")
        yield  # pragma: no cover - unreachable, keeps this a generator

    monkeypatch.setattr(orchestrator.client, "stream_chat", _broken_stream)

    with caplog.at_level("DEBUG"), pytest.raises(RuntimeError):
        list(orchestrator.stream_route([{"role": "user", "content": "hello"}]))

    assert "stream.route_started agent_id=" in caplog.text
    assert "stream.route_failed agent_id=" in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert "synthetic mid-stream failure" not in caplog.text


def test_stream_route_debug_logs_absent_by_default(caplog) -> None:
    """Streaming route logs stay silent without DEBUG, matching every other call site."""
    orchestrator = build()
    list(orchestrator.stream_route([{"role": "user", "content": "hello"}]))
    assert "stream.route_started" not in caplog.text
    assert "stream.route_completed" not in caplog.text


def test_stream_send_provider_request_debug_log_matches_non_streaming_event(
    monkeypatch, caplog
) -> None:
    """_stream_send reuses the exact provider.request event non-streaming _send emits.

    Same event name and bounded shape as
    test_provider_request_and_retry_debug_logs_are_bounded's non-streaming
    assertion -- proving the provider-request boundary is now visible for a
    real (non-mock) streaming call too, not a new, streaming-only event.
    """
    client = ModelClient(max_retries=0)
    agent = ModelAgent(
        "streaming_agent",
        "model-y",
        base_url="https://provider.example/v1",
        credential_key="",
    )

    @contextmanager
    def fake_open(request, destination=None, timeout=None):  # noqa: ARG001
        yield io.BytesIO(b"data: [DONE]\n\n")

    monkeypatch.setattr(client, "_validate_provider", lambda unused: None)
    monkeypatch.setattr(client, "_open_provider", fake_open)

    with caplog.at_level("DEBUG"):
        list(client.stream_chat(agent, [{"role": "user", "content": "hello"}]))

    assert (
        "provider.request agent_id=streaming_agent model=model-y provider= host=provider.example"
        in caplog.text
    )


def test_stream_send_provider_request_debug_log_absent_without_debug_level(monkeypatch, caplog) -> None:
    """The streaming provider.request log stays silent at the default level too."""
    client = ModelClient(max_retries=0)
    agent = ModelAgent(
        "quiet_streaming_agent",
        "model-z",
        base_url="https://provider.example/v1",
        credential_key="",
    )

    @contextmanager
    def fake_open(request, destination=None, timeout=None):  # noqa: ARG001
        yield io.BytesIO(b"data: [DONE]\n\n")

    monkeypatch.setattr(client, "_validate_provider", lambda unused: None)
    monkeypatch.setattr(client, "_open_provider", fake_open)

    list(client.stream_chat(agent, [{"role": "user", "content": "hello"}]))
    assert "provider.request" not in caplog.text


# -- HTTP request/response lifecycle (server.py) -----------------------------


def test_request_received_debug_log_reports_bounded_method_and_path(monkeypatch, caplog) -> None:
    """parse_request's DEBUG entry reports method/path only, never a query string."""
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

        assert "http_request_received method=POST path=/v1/chat/completions" in caplog.text
        assert "leaked-secret-token" not in caplog.text
    finally:
        server.server_close()


def test_log_request_only_captures_status_and_never_logs_by_itself(caplog) -> None:
    """log_request fires when send_response STARTS (before body/stream content);

    it must only capture the status for handle_one_request's later completion
    log, never emit anything on its own -- otherwise a streamed response's
    latency would be measured at time-to-first-byte instead of full delivery.
    """
    server = build_server(SimpleNamespace(agents=[], candidates=[]), port=0)
    handler = server.RequestHandlerClass.__new__(server.RequestHandlerClass)
    try:
        with caplog.at_level("DEBUG"):
            handler.log_request(200)
        assert handler._debug_response_code == 200
        assert caplog.text == ""
    finally:
        server.server_close()


def test_response_completion_log_covers_full_streamed_duration_not_first_byte(
    monkeypatch, caplog
) -> None:
    """The completion log's latency covers the WHOLE response, including streamed frames.

    Regression for the bug Devin's review caught: log_request fires the
    instant send_response is called (headers only, before any SSE frame is
    written), so logging latency there would report only time-to-first-byte
    for a streaming chat.completion.chunk response. This simulates a
    streaming handler that calls log_request immediately (as _begin_sse does)
    and then keeps writing frames for a further, measurable delay before
    do_GET/do_POST returns -- proving the logged latency covers that full
    delay, not just the moment headers went out.
    """
    server = build_server(SimpleNamespace(agents=[], candidates=[]), port=0)
    handler = server.RequestHandlerClass.__new__(server.RequestHandlerClass)
    stream_delay_seconds = 0.05

    def fake_super_handle_one_request(self) -> None:
        self.command = "POST"
        self.path = "/v1/chat/completions"
        # Simulate _begin_sse(): headers/status sent immediately...
        self.log_request(200)
        # ...then simulate writing further SSE frames over real wall-clock
        # time, exactly as a long chat.completion.chunk stream would.
        time.sleep(stream_delay_seconds)

    monkeypatch.setattr(
        BaseHTTPRequestHandler, "handle_one_request", fake_super_handle_one_request
    )
    monkeypatch.setattr(handler, "_reset_session", lambda: None)

    try:
        with caplog.at_level("DEBUG"):
            handler.handle_one_request()

        assert caplog.text.count("http_response_sent") == 1
        match = re.search(r"latency_ms=(\d+(?:\.\d+)?)", caplog.text)
        assert match is not None, caplog.text
        logged_latency_ms = float(match.group(1))
        # If latency were measured at log_request's call (time-to-first-byte)
        # instead of after the full stream, this would be ~0, not >= the
        # simulated stream delay.
        assert logged_latency_ms >= stream_delay_seconds * 1000
        assert "http_response_sent method=POST path=/v1/chat/completions status=200" in caplog.text
    finally:
        server.server_close()


def test_http_request_lifecycle_debug_logs_absent_by_default(monkeypatch, caplog) -> None:
    """The same request/response lifecycle stays silent without DEBUG enabled."""
    server = build_server(SimpleNamespace(agents=[], candidates=[]), port=0)
    handler = server.RequestHandlerClass.__new__(server.RequestHandlerClass)

    def fake_super_handle_one_request(self) -> None:
        self.command = "GET"
        self.path = "/healthz"
        self.log_request(200)

    monkeypatch.setattr(
        BaseHTTPRequestHandler, "handle_one_request", fake_super_handle_one_request
    )
    monkeypatch.setattr(handler, "_reset_session", lambda: None)

    try:
        handler.handle_one_request()
        assert "http_request_received" not in caplog.text
        assert "http_response_sent" not in caplog.text
    finally:
        server.server_close()


def test_parse_request_debug_log_survives_a_malformed_request_target(
    monkeypatch, caplog
) -> None:
    """SEC/availability regression: an unparsable target must not crash DEBUG logging.

    Devin's review caught this: ``urllib.parse.urlparse`` raises
    ``ValueError`` ("Invalid IPv6 URL") on some malformed absolute-form
    request targets (an unmatched IPv6 bracket) that stdlib's own
    ``parse_request`` accepts without validating -- it only splits the
    request line on whitespace, never parses the target as a URL. The old
    unguarded ``urlparse`` call in the DEBUG log line raised *before*
    ``do_GET``/``do_POST`` ever ran, so ``parse_request`` itself crashed and
    the connection was dropped with no HTTP response at all whenever DEBUG
    logging happened to be enabled. It must now fall back to a bounded,
    query-free string instead.
    """
    server = build_server(SimpleNamespace(agents=[], candidates=[]), port=0)
    handler = server.RequestHandlerClass.__new__(server.RequestHandlerClass)
    malformed_target = "http://[::1:8080/foo?leaked-secret-token=1"

    def fake_super_parse_request(self) -> bool:
        self.command = "TRACE"
        self.path = malformed_target
        return True

    monkeypatch.setattr(BaseHTTPRequestHandler, "parse_request", fake_super_parse_request)

    try:
        with caplog.at_level("DEBUG"):
            assert handler.parse_request() is True
        assert "http_request_received method=TRACE" in caplog.text
        # Best-effort fallback: the query string is still stripped even
        # though the malformed target could not be run through urlparse.
        assert "leaked-secret-token" not in caplog.text
    finally:
        server.server_close()


def test_malformed_request_target_gets_identical_response_verbose_or_not(
    restore_root_logger,
) -> None:
    """Socket-level regression: verbose and non-verbose modes must respond identically.

    Reproduces Devin's finding end-to-end over a real socket: a malformed
    absolute-form request target combined with an unsupported method (no
    ``do_TRACE`` handler, so stdlib's own routing never touches the path)
    used to get a clean stdlib 501 response with DEBUG off, but silently
    dropped the connection -- zero bytes back -- with DEBUG on, because the
    debug-only ``urlparse`` call in ``parse_request`` raised before method
    dispatch. Both modes must now return the same response.
    """
    request = (
        b"TRACE http://[::1:8080/foo HTTP/1.1\r\n"
        b"Host: 127.0.0.1\r\n"
        b"Connection: close\r\n\r\n"
    )

    def _send(port: int) -> bytes:
        with socket.create_connection(("127.0.0.1", port), timeout=2) as connection:
            connection.sendall(request)
            chunks: list[bytes] = []
            while True:
                chunk = connection.recv(4096)
                if not chunk:
                    return b"".join(chunks)
                chunks.append(chunk)

    def _run(*, verbose: bool) -> bytes:
        logging.getLogger("contextual_orchestrator.server").setLevel(
            logging.DEBUG if verbose else logging.WARNING
        )
        server = build_server(
            TaskOrchestrator([ModelAgent("malformed_target_agent", "mock-agent")]),
            port=0,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            return _send(server.server_address[1])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def _drop_date_header(response: bytes) -> bytes:
        # Everything else about the two responses must be byte-identical;
        # only the ``Date:`` header legitimately differs between the two
        # sequential requests.
        return b"\r\n".join(
            line for line in response.split(b"\r\n") if not line.startswith(b"Date:")
        )

    quiet_response = _run(verbose=False)
    verbose_response = _run(verbose=True)

    assert quiet_response.startswith(b"HTTP/1.1 501 ")
    assert verbose_response.startswith(b"HTTP/1.1 501 "), (
        "verbose mode's debug-only request-target parsing must never drop "
        f"the connection instead of the normal HTTP response: {verbose_response!r}"
    )
    assert _drop_date_header(quiet_response) == _drop_date_header(verbose_response)


def test_debug_logs_bound_an_oversized_method_token(monkeypatch, caplog) -> None:
    """CodeRabbit review: an unbounded method token must not bloat DEBUG log lines.

    ``BaseHTTPRequestHandler`` bounds only the whole request line (65536
    bytes total, rejected with a 414 before ``parse_request`` ever runs) --
    never the method token by itself. A pathological request line
    (``"A" * 65000 + " / HTTP/1.1"``) would otherwise put tens of kilobytes
    into ``self.command`` and, unbounded, into both DEBUG log call sites for
    that request. Covers parse_request's entry log and handle_one_request's
    completion log.
    """
    server = build_server(SimpleNamespace(agents=[], candidates=[]), port=0)
    oversized_method = "A" * 65000

    def fake_super_parse_request(self) -> bool:
        self.command = oversized_method
        self.path = "/healthz"
        return True

    handler = server.RequestHandlerClass.__new__(server.RequestHandlerClass)
    monkeypatch.setattr(BaseHTTPRequestHandler, "parse_request", fake_super_parse_request)
    try:
        with caplog.at_level("DEBUG"):
            assert handler.parse_request() is True
        match = re.search(r"http_request_received method=(\S+) path=", caplog.text)
        assert match is not None, caplog.text
        assert match.group(1) == "A" * 32
        assert oversized_method not in caplog.text
    finally:
        server.server_close()

    caplog.clear()
    server = build_server(SimpleNamespace(agents=[], candidates=[]), port=0)
    handler = server.RequestHandlerClass.__new__(server.RequestHandlerClass)

    def fake_super_handle_one_request(self) -> None:
        self.command = oversized_method
        self.path = "/healthz"
        self.log_request(200)

    monkeypatch.setattr(
        BaseHTTPRequestHandler, "handle_one_request", fake_super_handle_one_request
    )
    monkeypatch.setattr(handler, "_reset_session", lambda: None)
    try:
        with caplog.at_level("DEBUG"):
            handler.handle_one_request()
        match = re.search(r"http_response_sent method=(\S+) path=", caplog.text)
        assert match is not None, caplog.text
        assert match.group(1) == "A" * 32
        assert oversized_method not in caplog.text
    finally:
        server.server_close()
