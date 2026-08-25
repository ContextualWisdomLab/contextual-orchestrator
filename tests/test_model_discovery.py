"""Model discovery: KV-driven provider model listing, offline via mocked HTTP."""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.credentials import (  # noqa: E402
    InMemoryCredentialBackend,
    register_credential,
    set_backend,
)
from contextual_orchestrator.cost_ledger import PriceBook  # noqa: E402
from contextual_orchestrator.kv_config import InMemoryConfigStore  # noqa: E402
from contextual_orchestrator.model_discovery import (  # noqa: E402
    PROVIDER_MODEL_SOURCES,
    DiscoveredModel,
    ProviderDiscoveryError,
    ProviderModelSource,
    _price_per_1k,
    agent_from_discovered,
    agent_id_for,
    discover_all_models,
    discover_provider_models,
    refresh_price_book,
    select_cheapest_discovered_agent,
    select_top_n_cheapest_discovered_agents,
)


@pytest.fixture(autouse=True)
def _fresh_backend():
    set_backend(InMemoryCredentialBackend())
    try:
        yield
    finally:
        set_backend(None)


class _Response:
    def __init__(self, payload: dict) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return self._body


OPENAI_SOURCE = ProviderModelSource(
    provider_name="openai",
    credential_name="OPENAI_API_KEY",
    list_url="https://api.openai.com/v1/models",
    chat_base_url="https://api.openai.com/v1",
)

EMBEDDING_SOURCE = ProviderModelSource(
    provider_name="embedding_provider",
    credential_name="EMBEDDING_API_KEY",
    list_url="https://embedding.example/v1/models",
    chat_base_url="https://embedding.example/v1",
    capabilities=("embedding",),
)

OPENROUTER_SOURCE = ProviderModelSource(
    provider_name="openrouter",
    credential_name="OPENROUTER_API_KEY",
    list_url="https://openrouter.ai/api/v1/models?output_modalities=text",
    chat_base_url="https://openrouter.ai/api/v1",
    capabilities=("chat",),
)

BYTEZ_SOURCE = ProviderModelSource(
    provider_name="bytez",
    credential_name="BYTEZ_API_KEY",
    list_url="https://api.bytez.com/models/v2/list/models",
    chat_base_url="https://api.bytez.com/models/v2/openai/v1",
    auth_scheme="Key",
    style="bytez",
    task_filter="chat",
    capabilities=("chat",),
)


def test_discover_provider_models_skips_when_credential_missing() -> None:
    assert discover_provider_models(OPENAI_SOURCE) == []


def test_discover_openai_compatible_parses_models_and_pricing() -> None:
    register_credential("OPENROUTER_API_KEY", "sk-router")
    payload = {
        "data": [
            {"id": "meta/llama-3.3", "pricing": {"prompt": "0.0000006", "completion": "0.0000012"}},
            {"id": "no-pricing-model"},
            {"missing": "id-field"},
        ]
    }
    seen_requests = []

    def urlopen(request, timeout=None):
        seen_requests.append(request)
        return _Response(payload)

    with patch("contextual_orchestrator.model_discovery.urllib.request.urlopen", side_effect=urlopen):
        discovered = discover_provider_models(OPENROUTER_SOURCE)

    assert seen_requests[0].get_header("Authorization") == "Bearer sk-router"
    assert seen_requests[0].full_url == "https://openrouter.ai/api/v1/models?output_modalities=text"
    assert [m.model_id for m in discovered] == ["meta/llama-3.3", "no-pricing-model"]
    priced = discovered[0]
    assert priced.prompt_price_per_1k == pytest.approx(0.0006)
    assert priced.completion_price_per_1k == pytest.approx(0.0012)
    assert discovered[1].prompt_price_per_1k is None
    assert all(model.capabilities == ("chat",) for model in discovered)


def test_discovery_preserves_operator_declared_source_capabilities() -> None:
    register_credential("EMBEDDING_API_KEY", "registered-secret")
    with patch(
        "contextual_orchestrator.model_discovery.urllib.request.urlopen",
        return_value=_Response({"data": [{"id": "embedding-deployment"}]}),
    ):
        discovered = discover_provider_models(EMBEDDING_SOURCE)

    assert discovered[0].capabilities == ("embedding",)


def test_default_sources_activate_only_provider_filtered_chat_catalogs() -> None:
    sources = {source.provider_name: source for source in PROVIDER_MODEL_SOURCES}

    assert sources["openai"].capabilities == ()
    assert sources["openrouter"].capabilities == ("chat",)
    assert sources["openrouter"].list_url.endswith("?output_modalities=text")
    assert sources["nvidia_nim"].capabilities == ("chat",)
    assert sources["nvidia_nim_sub"].capabilities == ("chat",)


def test_price_per_1k_rejects_underflowing_positive_value() -> None:
    """A nonzero per-token price that underflows to 0.0 in float stays unknown."""
    assert _price_per_1k("1e-10000") is None
    assert _price_per_1k(0) == 0.0
    assert _price_per_1k(0.000001) == pytest.approx(0.001)


def test_discover_bytez_parses_models_with_key_auth_scheme() -> None:
    register_credential("BYTEZ_API_KEY", "bytez-secret")
    payload = {
        "error": None,
        "output": [
            {"modelId": "0-hero/Matter-0.1-Slim-7B-C", "task": "chat", "meterPrice": "0.0006 / sec"},
        ],
    }
    seen_requests = []

    def urlopen(request, timeout=None):
        seen_requests.append(request)
        return _Response(payload)

    with patch("contextual_orchestrator.model_discovery.urllib.request.urlopen", side_effect=urlopen):
        discovered = discover_provider_models(BYTEZ_SOURCE)

    assert seen_requests[0].get_header("Authorization") == "Key bytez-secret"
    assert seen_requests[0].full_url == "https://api.bytez.com/models/v2/list/models?task=chat"
    assert len(discovered) == 1
    assert discovered[0].model_id == "0-hero/Matter-0.1-Slim-7B-C"
    assert discovered[0].auth_scheme == "Key"
    assert discovered[0].capabilities == ("chat",)
    # Bytez prices by GPU-second, not per-token: no fabricated per-1k estimate.
    assert discovered[0].prompt_price_per_1k is None


def test_discover_all_models_continues_after_one_provider_error() -> None:
    register_credential("OPENAI_API_KEY", "sk-openai")
    register_credential("OPENROUTER_API_KEY", "sk-router")

    def urlopen(request, timeout=None):
        if urllib.parse.urlsplit(request.full_url).hostname == "api.openai.com":
            raise urllib.error.URLError("connection refused")
        return _Response({"data": [{"id": "meta/llama-3.3"}]})

    with patch("contextual_orchestrator.model_discovery.urllib.request.urlopen", side_effect=urlopen):
        discovered, errors = discover_all_models((OPENAI_SOURCE, OPENROUTER_SOURCE))

    assert [m.model_id for m in discovered] == ["meta/llama-3.3"]
    assert len(errors) == 1
    assert errors[0].provider_name == "openai"
    assert errors[0].error_code == "transport_error"
    assert "connection refused" not in str(errors[0])
    assert errors[0].__cause__ is None


def test_agent_id_for_is_two_word_snake_case() -> None:
    discovered = DiscoveredModel(
        provider_name="openrouter",
        model_id="Meta/Llama-3.3-70B",
        credential_name="OPENROUTER_API_KEY",
        chat_base_url="https://openrouter.ai/api/v1",
        auth_scheme="Bearer",
    )
    assert agent_id_for(discovered) == "openrouter_meta_llama_3_3_70b"


def test_agent_from_discovered_builds_disabled_agent_with_correct_auth() -> None:
    discovered = DiscoveredModel(
        provider_name="bytez",
        model_id="0-hero/Matter-0.1-Slim-7B-C",
        credential_name="BYTEZ_API_KEY",
        chat_base_url="https://api.bytez.com/models/v2/openai/v1",
        auth_scheme="Key",
    )
    agent = agent_from_discovered(discovered, priority=3)
    assert agent.id == "bytez_0_hero_matter_0_1_slim_7b_c"
    assert agent.disabled is True
    assert agent.auth_scheme == "Key"
    assert agent.credential_key == "BYTEZ_API_KEY"
    assert agent.priority == 3
    assert "discovered" in agent.tags


def test_agent_from_discovered_preserves_explicit_capabilities() -> None:
    discovered = DiscoveredModel(
        provider_name="openai",
        model_id="embedding-deployment",
        credential_name="OPENAI_API_KEY",
        chat_base_url="https://api.openai.com/v1",
        auth_scheme="Bearer",
        capabilities=("embedding",),
    )

    assert agent_from_discovered(discovered).tags == ("discovered", "embedding")


def test_refresh_price_book_writes_known_pricing_and_skips_unpriced() -> None:
    price_book = PriceBook(InMemoryConfigStore())
    priced = DiscoveredModel(
        provider_name="openrouter",
        model_id="meta/llama-3.3",
        credential_name="OPENROUTER_API_KEY",
        chat_base_url="https://openrouter.ai/api/v1",
        auth_scheme="Bearer",
        prompt_price_per_1k=0.0006,
        completion_price_per_1k=0.0012,
    )
    unpriced = DiscoveredModel(
        provider_name="bytez",
        model_id="some/model",
        credential_name="BYTEZ_API_KEY",
        chat_base_url="https://api.bytez.com/models/v2/openai/v1",
        auth_scheme="Key",
    )
    written = refresh_price_book([priced, unpriced], price_book)
    assert written == 1
    entry = price_book.get_price("openrouter", "meta/llama-3.3")
    assert entry is not None
    assert entry.prompt_price_per_1k == pytest.approx(0.0006)
    assert price_book.get_price("bytez", "some/model") is None


def test_select_cheapest_discovered_agent_picks_the_lower_priced_candidate() -> None:
    from contextual_orchestrator.cost_ledger import PriceEntry

    price_book = PriceBook(InMemoryConfigStore())
    cheap = DiscoveredModel(
        provider_name="openrouter",
        model_id="small-cheap-model",
        credential_name="OPENROUTER_API_KEY",
        chat_base_url="https://openrouter.ai/api/v1",
        auth_scheme="Bearer",
    )
    pricey = DiscoveredModel(
        provider_name="nvidia_nim",
        model_id="large-pricey-model",
        credential_name="NVIDIA_NIM_API_KEY",
        chat_base_url="https://integrate.api.nvidia.com/v1",
        auth_scheme="Bearer",
    )
    price_book.set_price(PriceEntry("openrouter", "small-cheap-model", 0.1, 0.1))
    price_book.set_price(PriceEntry("nvidia_nim", "large-pricey-model", 5.0, 10.0))

    winner = select_cheapest_discovered_agent([pricey, cheap], price_book)
    assert winner is cheap


def test_select_cheapest_discovered_agent_returns_none_for_empty_list() -> None:
    price_book = PriceBook(InMemoryConfigStore())
    assert select_cheapest_discovered_agent([], price_book) is None


def test_select_top_n_cheapest_discovered_agents_orders_by_cost() -> None:
    from contextual_orchestrator.cost_ledger import PriceEntry

    price_book = PriceBook(InMemoryConfigStore())
    cheapest = DiscoveredModel("openrouter", "a", "OPENROUTER_API_KEY", "https://openrouter.ai/api/v1", "Bearer")
    middle = DiscoveredModel("nvidia_nim", "b", "NVIDIA_NIM_API_KEY", "https://integrate.api.nvidia.com/v1", "Bearer")
    priciest = DiscoveredModel("openai", "c", "OPENAI_API_KEY", "https://api.openai.com/v1", "Bearer")
    price_book.set_price(PriceEntry("openrouter", "a", 0.01, 0.01))
    price_book.set_price(PriceEntry("nvidia_nim", "b", 1.0, 1.0))
    price_book.set_price(PriceEntry("openai", "c", 5.0, 5.0))

    top_two = select_top_n_cheapest_discovered_agents([priciest, middle, cheapest], price_book, 2)
    assert top_two == [cheapest, middle]


def test_select_top_n_cheapest_discovered_agents_zero_limit_returns_empty() -> None:
    price_book = PriceBook(InMemoryConfigStore())
    model = DiscoveredModel("openai", "a", "OPENAI_API_KEY", "https://api.openai.com/v1", "Bearer")
    assert select_top_n_cheapest_discovered_agents([model], price_book, 0) == []


def test_sync_discovered_agents_adds_and_updates_idempotently() -> None:
    orchestrator = TaskOrchestrator([ModelAgent("seed_agent", "seed-model")])
    discovered = DiscoveredModel(
        provider_name="openrouter",
        model_id="meta/llama-3.3",
        credential_name="OPENROUTER_API_KEY",
        chat_base_url="https://openrouter.ai/api/v1",
        auth_scheme="Bearer",
    )
    agent_v1 = agent_from_discovered(discovered, priority=0)

    result = orchestrator.sync_discovered_agents([agent_v1])
    assert result == {"added": ["openrouter_meta_llama_3_3"], "updated": []}
    assert {a.id for a in orchestrator.candidates} == {"seed_agent", "openrouter_meta_llama_3_3"}

    agent_v2 = agent_from_discovered(discovered, priority=7)
    result = orchestrator.sync_discovered_agents([agent_v2])
    assert result == {"added": [], "updated": ["openrouter_meta_llama_3_3"]}
    stored = next(a for a in orchestrator.candidates if a.id == "openrouter_meta_llama_3_3")
    assert stored.priority == 7
    # No duplicate rows were appended on the update pass.
    assert len(orchestrator.candidates) == 2


def test_sync_discovered_agents_persists_when_agents_db_is_set(tmp_path) -> None:
    db_path = str(tmp_path / "pool.db")
    discovered = DiscoveredModel(
        provider_name="openai",
        model_id="gpt-5.5",
        credential_name="OPENAI_API_KEY",
        chat_base_url="https://api.openai.com/v1",
        auth_scheme="Bearer",
    )
    agent = agent_from_discovered(discovered)

    first = TaskOrchestrator([ModelAgent("seed_agent", "seed-model")], agents_db=db_path)
    first.sync_discovered_agents([agent])

    second = TaskOrchestrator([ModelAgent("seed_agent", "seed-model")], agents_db=db_path)
    assert any(a.id == "openai_gpt_5_5" for a in second.candidates)
