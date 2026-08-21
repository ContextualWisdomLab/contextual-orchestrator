from __future__ import annotations

from types import SimpleNamespace

import pytest

from contextual_orchestrator import ModelAgent, TaskOrchestrator
from contextual_orchestrator import __main__ as cli
from contextual_orchestrator.model_discovery import (
    DiscoveredModel,
    ProviderDiscoveryError,
)


def test_empty_gateway_seed_expands_from_its_registry(monkeypatch) -> None:
    seed = ModelAgent(
        "gateway_seed",
        "",
        base_url="https://gateway.example/v1",
        credential_key="LLM_GATEWAY_API_KEY",
        tags=("reasoning", "writing"),
    )

    monkeypatch.setattr(
        cli,
        "discover_provider_models",
        lambda source: [
            DiscoveredModel(
                provider_name=source.provider_name,
                model_id="chat-model",
                credential_name=source.credential_name,
                chat_base_url=source.chat_base_url,
                auth_scheme=source.auth_scheme,
            ),
            DiscoveredModel(
                provider_name=source.provider_name,
                model_id="text-embedding-model",
                credential_name=source.credential_name,
                chat_base_url=source.chat_base_url,
                auth_scheme=source.auth_scheme,
            ),
        ],
    )

    agents = cli._auto_discover_seed_agents([seed], allow_failures=False)

    assert [agent.model for agent in agents] == ["chat-model"]
    assert agents[0].disabled is False
    assert agents[0].base_url == "https://gateway.example/v1"


def test_gateway_seed_discovery_preserves_configured_and_disables_unusable_seeds(
    monkeypatch,
) -> None:
    configured = ModelAgent("configured_agent", "chat-model")
    assert cli._auto_discover_seed_agents([configured], allow_failures=False) == [configured]

    seed = ModelAgent("gateway_seed", "", base_url="https://gateway.example/v1")
    failure = ProviderDiscoveryError("gateway", "unavailable")
    monkeypatch.setattr(cli, "discover_provider_models", lambda _source: (_ for _ in ()).throw(failure))
    with pytest.raises(ProviderDiscoveryError):
        cli._auto_discover_seed_agents([seed], allow_failures=False)
    assert cli._auto_discover_seed_agents([seed], allow_failures=True)[0].disabled is True

    monkeypatch.setattr(
        cli,
        "discover_provider_models",
        lambda source: [
            DiscoveredModel(
                provider_name=source.provider_name,
                    model_id="text-embedding-model",
                    credential_name=source.credential_name,
                    chat_base_url=source.chat_base_url,
                    auth_scheme=source.auth_scheme,
                )
        ],
    )
    assert cli._auto_discover_seed_agents([seed], allow_failures=False)[0].disabled is True


def test_discover_models_command_fails_when_every_provider_fails(monkeypatch) -> None:
    monkeypatch.setattr(
        cli,
        "discover_all_models",
        lambda: ([], [SimpleNamespace(provider_name="gateway")]),
    )
    monkeypatch.setattr(cli, "refresh_price_book", lambda _models, _prices: 0)
    with pytest.raises(SystemExit) as captured:
        cli._discover_models_command([])
    assert captured.value.code == 1


def test_structured_output_forces_conduct_even_when_auto_would_route() -> None:
    orchestrator = TaskOrchestrator(
        [ModelAgent("general_agent", "mock-model", tags=("reasoning", "writing"))]
    )

    result = orchestrator.complete(
        [{"role": "user", "content": "short structured request"}],
        mode="auto",
        output_contract={"type": "json_object"},
    )

    assert result["mode"] == "conduct"
    assert len(result["trace"]) == 4
    assert result["answer"] == "{}"
