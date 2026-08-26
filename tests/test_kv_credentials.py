"""KV credential seam: resolution, credential_key mapping, and no-env-fallback.

These run entirely on the in-memory backend — no Postgres or KV service needed.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent  # noqa: E402
from contextual_orchestrator.credentials import (  # noqa: E402
    InMemoryCredentialBackend,
    NotConfigured,
    get_credential,
    register_credential,
    set_backend,
)
from contextual_orchestrator.orchestrator import ModelClient  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_backend():
    """Give every test an isolated in-memory KV and reset afterwards."""
    set_backend(InMemoryCredentialBackend())
    try:
        yield
    finally:
        set_backend(None)


def test_get_credential_returns_none_when_absent() -> None:
    assert get_credential("OPENAI_API_KEY") is None


def test_register_then_get_roundtrips_via_kv() -> None:
    register_credential("OPENAI_API_KEY", "sk-live-123")
    assert get_credential("OPENAI_API_KEY") == "sk-live-123"


def test_register_credential_overwrites() -> None:
    register_credential("OPENAI_API_KEY", "sk-old")
    register_credential("OPENAI_API_KEY", "sk-new")
    assert get_credential("OPENAI_API_KEY") == "sk-new"


def test_credential_key_defaults_to_openai() -> None:
    agent = ModelAgent("remote_agent", "gpt-example", "https://api.openai.com/v1")
    assert agent.credential_key == "OPENAI_API_KEY"
    assert agent.credential_name == "OPENAI_API_KEY"


def test_legacy_api_key_env_is_treated_as_credential_name_not_env() -> None:
    # A legacy api_key_env value maps to the credential NAME; it is never read
    # from the process environment.
    os.environ.pop("LEGACY_PROVIDER_KEY", None)
    os.environ["LEGACY_PROVIDER_KEY"] = "sk-from-env-should-be-ignored"
    try:
        agent = ModelAgent("legacy_agent", "gpt-example", "https://api.openai.com/v1", "LEGACY_PROVIDER_KEY")
        assert agent.credential_name == "LEGACY_PROVIDER_KEY"
        # Not registered in the KV -> unresolvable, despite the env var existing.
        assert get_credential(agent.credential_name) is None
        register_credential("LEGACY_PROVIDER_KEY", "sk-from-kv")
        assert get_credential(agent.credential_name) == "sk-from-kv"
    finally:
        os.environ.pop("LEGACY_PROVIDER_KEY", None)


def test_explicit_credential_key_resolves() -> None:
    agent = ModelAgent(
        "vendor_agent", "gpt-example", "https://api.openai.com/v1", credential_key="VENDOR_API_KEY"
    )
    assert agent.credential_name == "VENDOR_API_KEY"
    register_credential("VENDOR_API_KEY", "sk-vendor")
    assert get_credential(agent.credential_name) == "sk-vendor"


def test_non_mock_agent_without_credential_raises_not_env_fallback() -> None:
    # Even with a matching env var set, an unresolved KV credential must raise
    # NotConfigured rather than silently reading os.getenv.
    os.environ["OPENAI_API_KEY"] = "sk-env-must-not-be-used"
    try:
        client = ModelClient()
        agent = ModelAgent("remote_agent", "gpt-example", "https://api.openai.com/v1")
        with pytest.raises(NotConfigured) as exc:
            client._validate_provider(agent)
        assert "OPENAI_API_KEY" in str(exc.value)
    finally:
        os.environ.pop("OPENAI_API_KEY", None)


def test_mock_agent_stays_keyless() -> None:
    # Mock agents early-return before any credential logic; no KV required.
    client = ModelClient()
    agent = ModelAgent("general_agent", "mock-generalist", "mock://local")
    assert client.chat(agent, [{"role": "user", "content": "hi"}])


def test_unknown_backend_selector_raises(monkeypatch) -> None:
    from contextual_orchestrator import credentials

    set_backend(None)
    monkeypatch.setenv("CONTEXTUAL_ORCHESTRATOR_KV_BACKEND", "sqlite")
    with pytest.raises(NotConfigured):
        credentials.get_backend()
    set_backend(None)


def test_auth_scheme_defaults_to_bearer() -> None:
    agent = ModelAgent("remote_agent", "gpt-example", "https://api.openai.com/v1")
    assert agent.auth_scheme == "Bearer"


def test_non_bearer_auth_scheme_reaches_the_authorization_header() -> None:
    # Bytez (and similar providers) use "Key <token>" instead of "Bearer <token>".
    from unittest.mock import patch

    agent = ModelAgent(
        "bytez_agent",
        "some/model",
        base_url="https://api.bytez.com/models/v2/openai/v1",
        credential_key="BYTEZ_API_KEY",
        auth_scheme="Key",
    )
    register_credential("BYTEZ_API_KEY", "bytez-secret")
    client = ModelClient(max_retries=0)
    seen = []

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self) -> bytes:
            import json

            return json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode("utf-8")

    def open_provider(request, _destination=None):
        seen.append(request)
        return _Response()

    # This is an authorization-header unit test, not a live DNS conformance
    # test. Keep provider destination validation deterministic and exercise the
    # real request/header construction below it.
    with patch.object(
        client,
        "_validate_provider",
        return_value=(2, ("93.184.216.34", 443)),
    ), patch.object(client, "_open_provider", side_effect=open_provider):
        assert client.chat(agent, [{"role": "user", "content": "ping"}]) == "ok"
    assert seen[0].get_header("Authorization") == "Key bytez-secret"


def test_auth_scheme_rejects_empty_value() -> None:
    with pytest.raises(ValueError):
        ModelAgent("bad_agent", "gpt-example", "https://api.openai.com/v1", auth_scheme="")


def test_model_client_embedding_uses_provider_endpoint_and_usage() -> None:
    """Provider embeddings preserve auth, vector values, and reported usage."""
    from unittest.mock import patch

    agent = ModelAgent(
        "embedding_agent", "embedding-model",
        base_url="https://provider.example/v1",
        credential_key="EMBEDDING_API_KEY", tags=("embedding",),
    )
    register_credential("EMBEDDING_API_KEY", "embedding-secret")
    client = ModelClient(max_retries=0)
    seen = []
    seen_timeouts = []

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self) -> bytes:
            return json.dumps({
                "data": [{"embedding": [0.125, 0.875]}],
                "usage": {"prompt_tokens": 4},
            }).encode()

    def open_provider(request, _destination=None):
        seen.append(request)
        seen_timeouts.append(client._local.provider_transport_timeout)
        return _Response()

    with (
        patch.object(client, "_validate_provider", return_value=(2, ("127.0.0.1", 443))),
        patch.object(client, "_open_provider", side_effect=open_provider),
        patch("contextual_orchestrator.orchestrator.time.monotonic", return_value=10.0),
        client.request_settings(request_deadline_monotonic=15.0),
    ):
        vectors, token_count = client.embed_with_usage(agent, ["evidence"])

    assert vectors == [[0.125, 0.875]]
    assert token_count == 4
    assert seen[0].full_url == "https://provider.example/v1/embeddings"
    assert seen[0].get_header("Authorization") == "Bearer embedding-secret"
    assert seen_timeouts == [5.0]


def test_model_client_embedding_rejects_non_object_data_entry() -> None:
    """Malformed provider rows fail through the classified response boundary."""
    from unittest.mock import patch

    from contextual_orchestrator.orchestrator import ProviderResponseError

    agent = ModelAgent(
        "embedding_agent", "embedding-model",
        base_url="https://provider.example/v1", tags=("embedding",),
    )
    client = ModelClient(max_retries=0)
    with (
        patch.object(client, "_validate_provider", return_value=(2, ("127.0.0.1", 443))),
        patch.object(client, "_send_raw_with_retry", return_value={"data": ["invalid"]}),
        pytest.raises(ProviderResponseError),
    ):
        client.embed_with_usage(agent, ["evidence"])
