"""Tests for the trusted CI review gateway bootstrap."""

from __future__ import annotations

from contextlib import contextmanager
import logging
import sys
import threading
import traceback
from types import SimpleNamespace

import pytest

from contextual_orchestrator.credentials import (
    InMemoryCredentialBackend,
    NotConfigured,
    get_credential,
    set_backend,
)
from contextual_orchestrator.model_discovery import DiscoveredModel
from contextual_orchestrator import review_gateway


@pytest.fixture(autouse=True)
def _fresh_backend():
    """Give every gateway test an isolated in-memory credential registry."""
    set_backend(InMemoryCredentialBackend())
    try:
        yield
    finally:
        set_backend(None)


def _discovered(
    provider: str,
    model: str,
    credential: str,
    *,
    is_free: bool = True,
    evidence_only: bool = False,
    capabilities: tuple[str, ...] = ("chat",),
    input_modalities: tuple[str, ...] = ("text",),
    output_modalities: tuple[str, ...] = ("text",),
) -> DiscoveredModel:
    """Build one explicitly evidenced discovered candidate for the tests."""
    return DiscoveredModel(
        provider_name=provider,
        model_id=model,
        credential_name=credential,
        chat_base_url=f"https://{provider}.example/v1",
        auth_scheme="Bearer",
        prompt_price_per_1k=0.0 if is_free else 1.0,
        completion_price_per_1k=0.0 if is_free else 1.0,
        is_free=is_free,
        evidence_only=evidence_only,
        capabilities=capabilities,
        input_modalities=input_modalities,
        output_modalities=output_modalities,
    )


def _close_orchestrator(orchestrator: object) -> None:
    """Release and verify background workers owned by a test-built orchestrator."""
    close = getattr(orchestrator, "close", None)
    if not callable(close):
        raise AssertionError("test-built orchestrator does not expose close()")
    close()
    collector = getattr(orchestrator, "_openrouter_collector", None)
    thread = getattr(collector, "_thread", None)
    if thread is not None and thread.is_alive():
        raise AssertionError("OpenRouter uptime collector is still alive after close()")


@contextmanager
def _closed_orchestrator(orchestrator: object):
    """Report paired failures with the unchanged body error first and as cause."""
    primary: BaseException | None = None
    try:
        yield
    except BaseException as exc:
        primary = exc
        raise
    finally:
        secondary: BaseException | None = None
        try:
            _close_orchestrator(orchestrator)
        except BaseException as cleanup_error:
            if primary is None:
                raise
            secondary = cleanup_error
        if secondary is not None:
            raise BaseExceptionGroup(
                "test body and orchestrator cleanup both failed", [primary, secondary]
            ) from primary


@contextmanager
def _closed_captured_orchestrator(captured: dict[str, object]):
    """Report captured-owner cleanup failures alongside the unchanged body error."""
    primary: BaseException | None = None
    try:
        yield
    except BaseException as exc:
        primary = exc
        raise
    finally:
        orchestrator = captured.get("orchestrator")
        if orchestrator is not None:
            secondary: BaseException | None = None
            try:
                _close_orchestrator(orchestrator)
            except BaseException as cleanup_error:
                if primary is None:
                    raise
                secondary = cleanup_error
            if secondary is not None:
                raise BaseExceptionGroup(
                    "test body and orchestrator cleanup both failed", [primary, secondary]
                ) from primary


class _DummyCollectorThread:
    """Tiny stand-in for collector worker liveness checks."""

    def __init__(self, alive: bool) -> None:
        self._alive = alive

    def is_alive(self) -> bool:
        """Return the configured liveness state."""
        return self._alive


class _DummyCollector:
    """Tiny stand-in exposing a collector thread."""

    def __init__(self, alive: bool) -> None:
        self._thread = _DummyCollectorThread(alive)


class _DummyOrchestrator:
    """Tiny stand-in for cleanup helper contracts."""

    def __init__(self, *, alive: bool = False, close_error: BaseException | None = None) -> None:
        self._openrouter_collector = _DummyCollector(alive)
        self.close_error = close_error
        self.close_calls = 0

    def close(self) -> None:
        """Record close calls and optionally fail like a broken owned closer."""
        self.close_calls += 1
        if self.close_error is not None:
            raise self.close_error


def test_close_orchestrator_rejects_missing_close():
    """Cleanup helpers fail closed when no owned close seam exists."""
    with pytest.raises(AssertionError, match="does not expose close"):
        _close_orchestrator(object())


def test_close_orchestrator_reports_live_uptime_worker():
    """A returned close call alone is not accepted when the worker remains alive."""
    orchestrator = _DummyOrchestrator(alive=True)

    with pytest.raises(AssertionError, match="still alive"):
        _close_orchestrator(orchestrator)

    assert orchestrator.close_calls == 1


@pytest.mark.parametrize("captured", [False, True], ids=["direct", "captured"])
@pytest.mark.parametrize("fault", ["live-worker", "close-error"])
def test_closed_orchestrator_surfaces_combined_failure(captured, fault):
    """Body and cleanup errors remain distinct, pytest-visible group members."""
    release = threading.Event()
    worker = threading.Thread(target=release.wait, name="openrouter-uptime-v3-control")
    worker.start()
    primary = AssertionError("primary failure")
    cleanup_error = RuntimeError("cleanup failed")
    close_calls = []

    def close():
        close_calls.append("close")
        if fault == "close-error":
            release.set()
            worker.join(timeout=2)
            assert not worker.is_alive()
            raise cleanup_error

    orchestrator = SimpleNamespace(
        close=close, _openrouter_collector=SimpleNamespace(_thread=worker)
    )
    scope = (
        _closed_captured_orchestrator({"orchestrator": orchestrator})
        if captured else _closed_orchestrator(orchestrator)
    )
    try:
        with pytest.raises(BaseExceptionGroup) as excinfo:
            with scope:
                raise primary
        group = excinfo.value
        assert len(group.exceptions) == 2
        assert group.exceptions[0] is primary
        assert group.__cause__ is primary
        assert group.__context__ is primary
        assert close_calls == ["close"]
        rendered = "".join(traceback.format_exception(group))
        assert "primary failure" in rendered
        if fault == "live-worker":
            assert worker.is_alive()  # Observe helper failure before fixture recovery.
            assert isinstance(group.exceptions[1], AssertionError)
            assert "still alive" in str(group.exceptions[1])
            assert "still alive" in rendered
        else:
            assert not worker.is_alive()
            assert group.exceptions[1] is cleanup_error
            assert "cleanup failed" in rendered
    finally:
        # Independent recovery does not credit the owned closer with settlement.
        release.set()
        worker.join(timeout=2)
        assert not worker.is_alive()


@pytest.mark.parametrize("captured", [False, True], ids=["direct", "captured"])
def test_closed_orchestrator_preserves_body_only_failure(captured):
    """Successful cleanup propagates the original body exception unchanged."""
    orchestrator = _DummyOrchestrator()
    primary = AssertionError("primary failure")
    scope = (
        _closed_captured_orchestrator({"orchestrator": orchestrator})
        if captured else _closed_orchestrator(orchestrator)
    )
    with pytest.raises(AssertionError) as excinfo:
        with scope:
            raise primary
    assert excinfo.value is primary
    assert orchestrator.close_calls == 1


def test_closed_orchestrator_reports_cleanup_failure_without_primary():
    """A cleanup failure still fails the test when no primary error exists."""
    orchestrator = _DummyOrchestrator(close_error=RuntimeError("cleanup failed"))

    with pytest.raises(RuntimeError, match="cleanup failed"):
        with _closed_orchestrator(orchestrator):
            pass

    assert orchestrator.close_calls == 1


def test_build_review_orchestrator_registers_all_credentials_but_serves_free_sources(
    monkeypatch,
):
    """Registration is global while free-pool admission is source constrained."""
    discovered = [
        _discovered("openai", "gpt-review", "OPENAI_API_KEY"),
        _discovered("openrouter", "router-review", "OPENROUTER_API_KEY"),
        _discovered("nvidia_nim", "nim-review", "NVIDIA_NIM_API_KEY"),
    ]
    monkeypatch.setattr(review_gateway, "discover_all_models", lambda: (discovered, []))
    environment = {
        name: f"secret-{name.lower()}"
        for name in review_gateway.REVIEW_CREDENTIAL_NAMES
    }

    orchestrator = review_gateway.build_review_orchestrator(environment)
    with _closed_orchestrator(orchestrator):
        assert {agent.credential_key for agent in orchestrator.agents} == {
            "OPENROUTER_API_KEY",
            "NVIDIA_NIM_API_KEY",
        }
        assert all(not agent.disabled for agent in orchestrator.agents)
        assert all("cost:free" in agent.tags for agent in orchestrator.agents)
        assert all("input:text" in agent.tags for agent in orchestrator.agents)
        assert all("output:text" in agent.tags for agent in orchestrator.agents)
        assert {agent.priority for agent in orchestrator.agents} == {0}
        assert all(
            get_credential(name) == environment[name]
            for name in review_gateway.REVIEW_CREDENTIAL_NAMES
        )


def test_build_review_orchestrator_rejects_paid_rows(monkeypatch):
    """Provider eligibility cannot override explicit nonzero pricing evidence."""
    discovered = [
        _discovered(
            "openrouter",
            "paid-review",
            "OPENROUTER_API_KEY",
            is_free=False,
        )
    ]
    monkeypatch.setattr(review_gateway, "discover_all_models", lambda: (discovered, []))

    with pytest.raises(NotConfigured, match="eligible zero-cost"):
        review_gateway.build_review_orchestrator(
            {"OPENROUTER_API_KEY": "router-secret"}
        )


def test_build_review_orchestrator_never_routes_evidence_only_models(monkeypatch):
    """Evidence-only catalog rows are never review upstreams."""
    discovered = [
        _discovered(
            "bytez",
            "router-review",
            "OPENROUTER_API_KEY",
            evidence_only=True,
        )
    ]
    monkeypatch.setattr(review_gateway, "discover_all_models", lambda: (discovered, []))

    with pytest.raises(NotConfigured, match="eligible zero-cost"):
        review_gateway.build_review_orchestrator(
            {"OPENROUTER_API_KEY": "router-secret"}
        )


def test_build_review_orchestrator_excludes_explicit_non_chat_models(monkeypatch):
    """Structured capability evidence, not the credential source, governs chat fitness."""
    discovered = [
        _discovered(
            "openrouter",
            "embedding-model",
            "OPENROUTER_API_KEY",
            capabilities=("embeddings",),
            output_modalities=("embedding",),
        ),
        _discovered("openrouter", "review-model", "OPENROUTER_API_KEY"),
    ]
    monkeypatch.setattr(review_gateway, "discover_all_models", lambda: (discovered, []))

    orchestrator = review_gateway.build_review_orchestrator(
        {"OPENROUTER_API_KEY": "router-secret"}
    )
    with _closed_orchestrator(orchestrator):
        assert [agent.model for agent in orchestrator.agents] == ["review-model"]


def test_build_review_orchestrator_admits_free_image_chat_model_for_figure_review(
    monkeypatch,
):
    """Free text+image chat rows join the review pool for figure-bearing requests.

    Blind text ``orchestrator/free`` still cannot select them
    (:meth:`TaskOrchestrator._is_general_free_agent`); image-bearing free
    traffic uses :meth:`TaskOrchestrator._free_pool_agent_ids` instead.
    """
    discovered = [
        _discovered(
            "openrouter",
            "vision-review-model",
            "OPENROUTER_API_KEY",
            input_modalities=("text", "image"),
        )
    ]
    monkeypatch.setattr(review_gateway, "discover_all_models", lambda: (discovered, []))

    orchestrator = review_gateway.build_review_orchestrator(
        {"OPENROUTER_API_KEY": "router-secret"}
    )
    with _closed_orchestrator(orchestrator):
        assert [agent.model for agent in orchestrator.agents] == ["vision-review-model"]
        assert "input:image" in orchestrator.agents[0].tags
        assert not orchestrator._is_general_free_agent(orchestrator.agents[0])
        assert orchestrator._is_free_agent(orchestrator.agents[0])
        assert orchestrator._agent_supports_image_input(orchestrator.agents[0])


def test_build_review_orchestrator_unions_blind_free_and_image_chat_models(
    monkeypatch,
):
    """Text-only and text+image free rows both remain available after bootstrap."""
    discovered = [
        _discovered("openrouter", "text-review", "OPENROUTER_API_KEY"),
        _discovered(
            "openrouter",
            "vision-review",
            "OPENROUTER_API_KEY",
            input_modalities=("text", "image"),
        ),
    ]
    monkeypatch.setattr(review_gateway, "discover_all_models", lambda: (discovered, []))

    orchestrator = review_gateway.build_review_orchestrator(
        {"OPENROUTER_API_KEY": "router-secret"}
    )
    with _closed_orchestrator(orchestrator):
        assert {agent.model for agent in orchestrator.agents} == {
            "text-review",
            "vision-review",
        }


def test_build_review_orchestrator_fails_closed_without_credentials():
    """A sidecar cannot start without at least one registered provider key."""
    with pytest.raises(NotConfigured, match="provider credential"):
        review_gateway.build_review_orchestrator({})


def test_build_review_orchestrator_does_not_count_auth_as_provider_credential():
    """The gateway auth token cannot satisfy the provider bootstrap gate."""
    with pytest.raises(NotConfigured, match="provider credential"):
        review_gateway.build_review_orchestrator(
            {review_gateway.REVIEW_AUTH_CREDENTIAL_NAME: "local-review-token"}
        )


def test_build_review_orchestrator_fails_closed_without_discovered_models(monkeypatch):
    """A configured key without a usable model list cannot start the sidecar."""
    monkeypatch.setattr(review_gateway, "discover_all_models", lambda: ([], []))
    with pytest.raises(NotConfigured, match="no provider models"):
        review_gateway.build_review_orchestrator(
            {"OPENROUTER_API_KEY": "router-secret"}
        )


def test_main_starts_authenticated_gateway(monkeypatch):
    """The CLI passes the generated local token into the protected server."""
    discovered = [
        _discovered("openrouter", "review-model", "OPENROUTER_API_KEY")
    ]
    monkeypatch.setattr(review_gateway, "discover_all_models", lambda: (discovered, []))
    captured: dict[str, object] = {}

    def fake_serve(orchestrator, **kwargs):
        """Capture server startup without binding a test port."""
        captured["orchestrator"] = orchestrator
        captured.update(kwargs)

    monkeypatch.setattr(review_gateway, "serve", fake_serve)
    monkeypatch.setenv("OPENROUTER_API_KEY", "router-secret")
    monkeypatch.setenv("CONTEXTUAL_ORCHESTRATOR_TOKEN", "local-review-token")
    monkeypatch.setattr(sys, "argv", ["review_gateway", "--port", "18181"])

    with _closed_captured_orchestrator(captured):
        review_gateway.main()

        assert captured["host"] == "127.0.0.1"
        assert captured["port"] == 18181
        security = captured["security"]
        assert security.auth_token == "local-review-token"
        assert security.allow_public_bind is False
        assert security.max_body_bytes == review_gateway.REVIEW_MAX_BODY_BYTES
        assert review_gateway.REVIEW_MAX_BODY_BYTES == 32 * 1024 * 1024
        assert get_credential(review_gateway.REVIEW_AUTH_CREDENTIAL_NAME) == "local-review-token"


def test_main_configures_redacted_logging_before_discovery(monkeypatch, capsys):
    """INFO sends discovery and request summaries to redacted stderr."""
    discovered = [
        _discovered("openrouter", "review-model", "OPENROUTER_API_KEY")
    ]

    def fake_discover():
        """Emit a discovery record before the server starts."""
        logging.getLogger("contextual_orchestrator.model_discovery").info(
            "discovery_complete token=non-credential-fixture"
        )
        return discovered, []

    monkeypatch.setattr(review_gateway, "discover_all_models", fake_discover)
    def fake_serve(orchestrator, **kwargs):
        """Emit one redacted summary and close the test-owned orchestrator."""
        with _closed_orchestrator(orchestrator):
            logging.getLogger("contextual_orchestrator.server").info(
                "http_request status=200 latency_ms=1 request_id=test-request"
            )

    monkeypatch.setattr(review_gateway, "serve", fake_serve)
    monkeypatch.setenv("OPENROUTER_API_KEY", "router-secret")
    monkeypatch.setenv("CONTEXTUAL_ORCHESTRATOR_TOKEN", "local-review-token")
    monkeypatch.setattr(sys, "argv", ["review_gateway", "--log-level", "info"])

    review_gateway.main()

    stderr = capsys.readouterr().err
    assert "discovery_complete token=[REDACTED]" in stderr
    assert "http_request status=200 latency_ms=1 request_id=test-request" in stderr
    assert "non-credential-fixture" not in stderr


def test_main_forwards_repeated_credential_array_to_candidate_scope(monkeypatch):
    """CLI deployments can explicitly constrain the bootstrap provider array."""
    discovered = [
        _discovered("bytez", "bytez-review", "BYTEZ_API_KEY"),
        _discovered("openrouter", "router-review", "OPENROUTER_API_KEY"),
    ]
    monkeypatch.setattr(review_gateway, "discover_all_models", lambda: (discovered, []))
    captured: dict[str, object] = {}

    def fake_serve(orchestrator, **kwargs):
        """Capture the CLI-selected serving pool without binding a port."""
        captured["orchestrator"] = orchestrator
        captured.update(kwargs)

    monkeypatch.setattr(review_gateway, "serve", fake_serve)
    monkeypatch.setenv("BYTEZ_API_KEY", "bytez-secret")
    monkeypatch.setenv("OPENROUTER_API_KEY", "router-secret")
    monkeypatch.setenv("CONTEXTUAL_ORCHESTRATOR_TOKEN", "local-review-token")
    monkeypatch.setattr(
        sys,
        "argv",
        ["review_gateway", "--credential-name", "BYTEZ_API_KEY"],
    )

    with _closed_captured_orchestrator(captured):
        review_gateway.main()

        orchestrator = captured["orchestrator"]
        assert [agent.credential_key for agent in orchestrator.agents] == ["BYTEZ_API_KEY"]


def test_main_requires_authentication(monkeypatch):
    """The sidecar never starts an unauthenticated inference endpoint."""
    monkeypatch.delenv("CONTEXTUAL_ORCHESTRATOR_TOKEN", raising=False)
    monkeypatch.setattr(sys, "argv", ["review_gateway"])

    with pytest.raises(SystemExit, match="CONTEXTUAL_ORCHESTRATOR_TOKEN"):
        review_gateway.main()


def test_build_review_orchestrator_admits_every_evidence_eligible_candidate(monkeypatch):
    """Review admission cannot evict eligible models through an arbitrary pool cap."""
    discovered = [
        _discovered(
            "openrouter",
            f"review-model-{index:02d}",
            "OPENROUTER_API_KEY",
        )
        for index in range(13)
    ]
    monkeypatch.setattr(review_gateway, "discover_all_models", lambda: (discovered, []))

    orchestrator = review_gateway.build_review_orchestrator(
        {"OPENROUTER_API_KEY": "router-secret"}
    )
    with _closed_orchestrator(orchestrator):
        assert {agent.model for agent in orchestrator.agents} == {
            model.model_id for model in discovered
        }
        assert len(orchestrator.agents) == len(discovered)
        assert {agent.priority for agent in orchestrator.agents} == {0}


def test_review_gateway_cli_has_no_decision_affecting_model_cap():
    """The trusted sidecar exposes no hand-tuned candidate-count admission control."""
    assert "--max-agents" not in review_gateway._build_parser().format_help()


def test_build_review_orchestrator_sizes_failover_budget_to_the_admitted_pool(monkeypatch):
    """A large free pool must not give up after the generic 2-attempt default.

    ``TaskOrchestrator`` defaults ``tool_retry_attempts`` to 1 (route_once tries
    at most 2 candidates) for every caller. The org's opencode-review-dispatch
    workflow calls ``orchestrator/free`` exactly once per PR review
    (``OPENCODE_MODEL_ATTEMPTS=1``, ``OPENCODE_POOL_MAX_CYCLES=1``) and falls
    back to a model-unavailable evidence-only review on any rejected/failed
    answer. With a dozen-plus discovered free candidates, capping our own
    internal failover at 2 wastes the rest of the catalog and manufactures
    exactly the "gives up after a few shallow attempts" fallback the workflow
    then has to absorb. The failover budget must scale with the admitted pool,
    bounded by the documented hard ceiling.
    """
    from contextual_orchestrator.tool_fallback import MAX_TOOL_RETRY_ATTEMPTS

    discovered = [
        _discovered(
            "openrouter",
            f"review-model-{index:02d}",
            "OPENROUTER_API_KEY",
        )
        for index in range(13)
    ]
    monkeypatch.setattr(review_gateway, "discover_all_models", lambda: (discovered, []))

    orchestrator = review_gateway.build_review_orchestrator(
        {"OPENROUTER_API_KEY": "router-secret"}
    )
    with _closed_orchestrator(orchestrator):
        assert orchestrator.tool_retry_attempts == MAX_TOOL_RETRY_ATTEMPTS


def test_build_review_orchestrator_never_exceeds_a_small_pool(monkeypatch):
    """The failover budget cannot exceed the number of candidates actually admitted."""
    discovered = [_discovered("openrouter", "solo-review", "OPENROUTER_API_KEY")]
    monkeypatch.setattr(review_gateway, "discover_all_models", lambda: (discovered, []))

    orchestrator = review_gateway.build_review_orchestrator(
        {"OPENROUTER_API_KEY": "router-secret"}
    )
    with _closed_orchestrator(orchestrator):
        assert orchestrator.tool_retry_attempts == 0
