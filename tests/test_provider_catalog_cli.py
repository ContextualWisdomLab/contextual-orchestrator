"""CLI wiring for catalog-backed provider discovery and runtime startup."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import contextual_orchestrator.__main__ as cli  # noqa: E402
from contextual_orchestrator import ModelAgent  # noqa: E402
from contextual_orchestrator.provider_catalog import ProviderCatalogUnavailable  # noqa: E402


class _Parser:
    """Small parser double that records fail-closed usage errors."""

    def error(self, message: str) -> None:
        """Raise a deterministic exception carrying the parser error text."""
        raise ValueError(message)


class _RuntimeOrchestrator:
    """CLI-facing orchestrator double for catalog startup tests."""

    instances: list["_RuntimeOrchestrator"] = []

    def __init__(self, agents, **kwargs) -> None:
        self.agents = agents
        self.kwargs = kwargs
        self.complete_calls: list[tuple[list[dict[str, str]], str]] = []
        type(self).instances.append(self)

    def complete(self, messages, mode="auto"):
        """Record one completion and return a deterministic response."""
        self.complete_calls.append((messages, mode))
        return {"answer": "catalog-answer", "mode": mode}

    def compare_to_baseline(self, prompts, mode="auto"):
        """Return a deterministic evaluation response for interface completeness."""
        return {"prompts": prompts, "mode": mode}


def _catalog_agent() -> ModelAgent:
    """Return one valid discovered agent fixture."""
    return ModelAgent(
        "openai_catalog_agent",
        "catalog-model",
        "https://api.openai.com/v1",
        credential_key="OPENAI_API_KEY",
        provider_name="openai",
    )


def test_runtime_agents_uses_seed_loader_without_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    """The explicit seed-file path remains unchanged when no durable DSN is selected."""
    expected = [_catalog_agent()]
    monkeypatch.setattr(cli, "load_agents", lambda path: expected if path == "agents.json" else [])
    args = argparse.Namespace(provider_catalog_dsn=None, agents="agents.json")
    assert cli._runtime_agents(_Parser(), args) is expected


def test_runtime_agents_loads_catalog_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    """A configured durable DSN replaces the seed file with enabled catalog models."""
    expected = [_catalog_agent()]
    stores: list[str] = []

    class _Store:
        def __init__(self, dsn: str) -> None:
            stores.append(dsn)

    class _Service:
        def __init__(self, *, store) -> None:
            self.store = store

        def candidate_agents(self):
            return expected

    monkeypatch.setattr(cli, "PostgresProviderCatalogStore", _Store)
    monkeypatch.setattr(cli, "ProviderCatalogService", _Service)
    args = argparse.Namespace(provider_catalog_dsn="postgresql://catalog", agents="ignored.json")

    assert cli._runtime_agents(_Parser(), args) is expected
    assert stores == ["postgresql://catalog"]


def test_runtime_agents_reports_catalog_initialization_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Durable catalog errors reach argparse without a silent seed or memory fallback."""
    monkeypatch.setattr(
        cli,
        "PostgresProviderCatalogStore",
        lambda _dsn: (_ for _ in ()).throw(ProviderCatalogUnavailable("catalog unavailable")),
    )
    args = argparse.Namespace(provider_catalog_dsn="postgresql://catalog", agents="ignored.json")
    with pytest.raises(ValueError, match="catalog unavailable"):
        cli._runtime_agents(_Parser(), args)


def test_runtime_agents_rejects_empty_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    """An initialized but empty catalog cannot fall back to the bundled mock pool."""
    monkeypatch.setattr(cli, "PostgresProviderCatalogStore", lambda _dsn: object())

    class _Service:
        def __init__(self, *, store) -> None:
            self.store = store

        def candidate_agents(self):
            return []

    monkeypatch.setattr(cli, "ProviderCatalogService", _Service)
    args = argparse.Namespace(provider_catalog_dsn="postgresql://catalog", agents="ignored.json")
    with pytest.raises(ValueError, match="no enabled candidates"):
        cli._runtime_agents(_Parser(), args)


def test_main_catalog_mode_uses_provider_aware_client(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Catalog mode wires the provider-aware client into the ordinary orchestrator."""
    _RuntimeOrchestrator.instances.clear()
    agent = _catalog_agent()
    client_calls: list[dict[str, object]] = []
    monkeypatch.setattr(cli, "_runtime_agents", lambda _parser, _args: [agent])
    monkeypatch.setattr(
        cli,
        "ProviderAwareModelClient",
        lambda **kwargs: client_calls.append(kwargs) or {"provider_client": kwargs},
    )
    monkeypatch.setattr(cli, "TaskOrchestrator", _RuntimeOrchestrator)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "contextual-orchestrator",
            "catalog prompt",
            "--provider-catalog-dsn",
            "postgresql://catalog",
            "--mode",
            "route",
        ],
    )

    cli.main()

    instance = _RuntimeOrchestrator.instances[-1]
    assert instance.agents == [agent]
    assert instance.kwargs["client"]["provider_client"]["verify_tls"] is True
    assert client_calls == [{"ca_bundle": None, "verify_tls": True}]
    assert instance.complete_calls == [([{"role": "user", "content": "catalog prompt"}], "route")]
    assert json.loads(capsys.readouterr().out) == {"answer": "catalog-answer", "mode": "route"}
