"""Regression coverage for isolating non-chat models from chat agent discovery."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator.credentials import (  # noqa: E402
    InMemoryCredentialBackend,
    register_credential,
    set_backend,
)
from contextual_orchestrator.cost_ledger import PriceBook, PriceEntry  # noqa: E402
from contextual_orchestrator.kv_config import InMemoryConfigStore  # noqa: E402
from contextual_orchestrator.model_discovery import (  # noqa: E402
    DiscoveredModel,
    ProviderModelSource,
    agent_from_discovered,
    discover_provider_models,
    is_chat_compatible_model_id,
    refresh_price_book,
    select_cheapest_discovered_agent,
    select_top_n_cheapest_discovered_agents,
)


class _Response:
    """Small context-managed HTTP response used by the offline regression."""

    def __init__(self, payload: dict[str, object]) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_args: object) -> bool:
        return False

    def read(self, _size: int = -1) -> bytes:
        return self._body


@pytest.fixture(autouse=True)
def _fresh_credential_backend():
    """Keep the provider credential registry isolated between tests."""
    set_backend(InMemoryCredentialBackend())
    try:
        yield
    finally:
        set_backend(None)


def _model(model_id: str, *, priced: bool = False) -> DiscoveredModel:
    """Build one synthetic discovered model for capability-boundary tests."""
    return DiscoveredModel(
        provider_name="enterprise_gateway",
        model_id=model_id,
        credential_name="GATEWAY_API_KEY",
        chat_base_url="https://gateway.example.test/v1",
        auth_scheme="Bearer",
        prompt_price_per_1k=1.0 if priced else None,
        completion_price_per_1k=1.0 if priced else None,
    )


def test_embedding_deployments_never_enter_chat_agent_discovery() -> None:
    """Exclude the exact Azure embedding deployment seen in synthesis alerts."""
    register_credential("GATEWAY_API_KEY", "gateway-secret")
    source = ProviderModelSource(
        provider_name="enterprise_gateway",
        credential_name="GATEWAY_API_KEY",
        list_url="https://gateway.example.test/v1/models",
        chat_base_url="https://gateway.example.test/v1",
    )
    payload = {
        "data": [
            {"id": "azure/text-embedding-3-large"},
            {"id": "text_embedding_3_large"},
            {"id": "BAAI/bge-m3"},
            {"id": "openai/whisper-1"},
            {"id": "gpt-4o-mini-transcribe"},
            {"id": "text-moderation-latest"},
            {"id": "company/reranker-v2"},
            {"id": "gpt-5.2"},
            {"id": "qwen/qwen3-235b-a22b-instruct"},
        ]
    }

    with patch(
        "contextual_orchestrator.model_discovery.urllib.request.urlopen",
        return_value=_Response(payload),
    ):
        discovered = discover_provider_models(source)

    assert [model.model_id for model in discovered] == [
        "gpt-5.2",
        "qwen/qwen3-235b-a22b-instruct",
    ]


@pytest.mark.parametrize(
    ("model_id", "expected"),
    [
        (None, False),
        ("", False),
        ("---", False),
        ("vendor/embeddingv2", False),
        ("vendor/reranking-v2", False),
        ("vendor/transcriber-v2", False),
        ("gpt-5.2", True),
        ("qwen/qwen3-instruct", True),
    ],
)
def test_chat_compatibility_normalizes_identifiers(
    model_id: object, expected: bool
) -> None:
    """Normalize provider prefixes and separators without guessing chat features."""
    assert is_chat_compatible_model_id(model_id) is expected  # type: ignore[arg-type]


def test_bytez_chat_catalog_still_rejects_non_chat_identifiers() -> None:
    """Apply the same boundary even when a provider accepts a chat task filter."""
    register_credential("BYTEZ_API_KEY", "bytez-secret")
    source = ProviderModelSource(
        provider_name="bytez",
        credential_name="BYTEZ_API_KEY",
        list_url="https://api.bytez.com/models/v2/list/models",
        chat_base_url="https://api.bytez.com/models/v2/openai/v1",
        auth_scheme="Key",
        style="bytez",
        task_filter="chat",
    )
    payload = {
        "output": [
            {"modelId": "vendor/embeddingv2"},
            {"modelId": "vendor/chat-instruct"},
        ]
    }

    with patch(
        "contextual_orchestrator.model_discovery.urllib.request.urlopen",
        return_value=_Response(payload),
    ):
        discovered = discover_provider_models(source)

    assert [model.model_id for model in discovered] == ["vendor/chat-instruct"]


def test_non_chat_discovery_cannot_be_converted_to_agent() -> None:
    """Keep manually constructed discovery rows from bypassing the parser filter."""
    with pytest.raises(ValueError, match="non-chat model"):
        agent_from_discovered(_model("azure/text-embedding-3-large"))


def test_non_chat_discovery_is_not_priced_or_selected_for_chat() -> None:
    """Keep price routing from reintroducing an incompatible endpoint model."""
    price_book = PriceBook(InMemoryConfigStore())
    embedding_model = _model("azure/text-embedding-3-large", priced=True)
    chat_model = _model("gpt-5.2", priced=True)
    price_book.set_price(PriceEntry("enterprise_gateway", "gpt-5.2", 1.0, 1.0))

    assert refresh_price_book([embedding_model, chat_model], price_book) == 1
    assert price_book.get_price(
        "enterprise_gateway", "azure/text-embedding-3-large"
    ) is None
    assert select_cheapest_discovered_agent([embedding_model], price_book) is None
    assert select_top_n_cheapest_discovered_agents(
        [embedding_model], price_book, 1
    ) == []
