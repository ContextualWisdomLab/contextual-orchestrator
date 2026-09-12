from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from contextual_orchestrator.credentials import InMemoryCredentialBackend, register_credential, set_backend
from contextual_orchestrator.model_discovery import (
    PROVIDER_MODEL_SOURCES,
    discover_provider_models,
)
from contextual_orchestrator.provider_bootstrap import (
    PROVIDER_CREDENTIAL_NAMES,
    collect_provider_credentials,
)


class _Response:
    """Minimal context-managed response used by the discovery transport stub."""

    def __init__(self, payload: dict) -> None:
        """Encode the supplied JSON payload as the response body."""
        self._body = json.dumps(payload).encode()

    def __enter__(self):
        """Return this response when the mocked request is opened."""
        return self

    def __exit__(self, *_args):
        """Leave exception handling to the discovery test context."""
        return False

    def read(self, amt: int | None = None) -> bytes:
        """Return the complete body or the requested prefix."""
        return self._body if amt is None else self._body[:amt]


@pytest.fixture(autouse=True)
def isolated_credential_backend():
    """Give each discovery test an isolated in-memory credential registry."""
    set_backend(InMemoryCredentialBackend())
    yield
    set_backend(None)


def test_experiential_labs_discovery_uses_kv_and_preserves_unknown_evidence() -> None:
    """Keep KV authentication while leaving absent catalog evidence unknown."""
    source = next(
        item for item in PROVIDER_MODEL_SOURCES if item.provider_name == "experiential_labs"
    )
    assert source.credential_name == "EXPERIENTAL_LABS_API_KEY"
    assert source.list_url == "https://api.experientiallabs.ai/v1/models"
    assert source.chat_base_url == "https://api.experientiallabs.ai/v1"
    assert source.bootstrap_required is False

    register_credential(source.credential_name, "experiential-secret")

    def mocked_request(request, timeout=None, **_kwargs):
        """Assert the trusted catalog request and return its minimal payload."""
        assert request.full_url == source.list_url
        assert request.get_header("Authorization") == "Bearer experiential-secret"
        return _Response({"data": [{"id": "experiential/model"}]})

    with patch(
        "contextual_orchestrator.model_discovery._open_trusted_discovery_request",
        side_effect=mocked_request,
    ):
        discovered = discover_provider_models(source)

    assert [model.model_id for model in discovered] == ["experiential/model"]
    assert discovered[0].prompt_price_per_1k is None
    assert discovered[0].completion_price_per_1k is None
    assert discovered[0].privacy_policy_urls == ()
    assert discovered[0].supports_zero_data_retention is None
    assert discovered[0].zdr_capable is False
    assert discovered[0].is_free is False


def test_experiential_labs_credential_is_optional_during_complete_bootstrap() -> None:
    """Allow bootstrap without the optional key while retaining a supplied key."""
    credential_values = {name: "existing-key" for name in PROVIDER_CREDENTIAL_NAMES}
    assert "EXPERIENTAL_LABS_API_KEY" not in credential_values
    assert collect_provider_credentials(credential_values) == credential_values
    credential_values["EXPERIENTAL_LABS_API_KEY"] = "experiential-key"
    assert collect_provider_credentials(credential_values) == credential_values
