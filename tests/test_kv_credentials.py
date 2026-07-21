"""KV credential seam: resolution, credential_key mapping, and no-env-fallback.

These run entirely on the in-memory backend — no Postgres or KV service needed.
"""

from __future__ import annotations

import io
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


def test_serve_can_seed_in_memory_credential_from_stdin(monkeypatch) -> None:
    from contextual_orchestrator import __main__ as cli

    observed: dict[str, str | None] = {}

    def fake_serve(*_args, **_kwargs) -> None:
        observed["credential"] = get_credential("OPENAI_API_KEY")

    monkeypatch.setattr(cli, "serve", fake_serve)
    monkeypatch.setattr(sys, "stdin", io.StringIO("\ufeffsk-stdin-bootstrap\n"))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "contextual-orchestrator",
            "--serve",
            "--agents",
            "examples/agents.mock.json",
            "--auth-token",
            "pilot-token",
            "--bootstrap-credential-stdin",
            "OPENAI_API_KEY",
        ],
    )

    cli.main()

    assert observed == {"credential": "sk-stdin-bootstrap"}
