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
from contextual_orchestrator.model_discovery import (  # noqa: E402
    ProviderModelSource,
    discover_provider_models,
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
