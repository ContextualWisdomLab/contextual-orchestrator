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
from contextual_orchestrator.__main__ import _register_credential_command  # noqa: E402
from contextual_orchestrator.credentials import (  # noqa: E402
    InMemoryCredentialBackend,
    NotConfigured,
    get_backend,
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


def test_register_credential_from_env_strips_mounted_secret_newline() -> None:
    """A Docker/K8s secret trailing newline must not persist or reach the provider.

    Buyer next action: ``register-credential --from-env OPENAI_API_KEY`` from a
    mounted secret, then send traffic. The upstream Authorization header must
    be ``Bearer sk-…`` with no newline.
    """
    previous = os.environ.get("OPENAI_API_KEY")
    os.environ["OPENAI_API_KEY"] = "sk-live-invoice-key\n"
    captured: dict[str, str] = {}
    try:
        _register_credential_command(["--name", "OPENAI_API_KEY", "--from-env", "OPENAI_API_KEY"])
        assert get_backend().get("OPENAI_API_KEY") == "sk-live-invoice-key"
        assert get_credential("OPENAI_API_KEY") == "sk-live-invoice-key"

        client = ModelClient()

        def _capture(request):
            captured["authorization"] = request.get_header("Authorization")

            class _Resp:
                def read(self):
                    return json.dumps(
                        {
                            "choices": [{"message": {"content": "invoice posted"}}],
                            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
                        }
                    ).encode()

                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    return False

            return _Resp()

        client._open_provider = _capture  # type: ignore[method-assign]
        agent = ModelAgent("remote_agent", "gpt-example", "https://api.openai.com/v1")
        reply = client._send(
            agent,
            {"model": "gpt-example", "messages": [{"role": "user", "content": "post the invoice"}]},
        )
        assert reply == "invoice posted"
        assert captured["authorization"] == "Bearer sk-live-invoice-key"
        assert "\n" not in captured["authorization"]
    finally:
        if previous is None:
            os.environ.pop("OPENAI_API_KEY", None)
        else:
            os.environ["OPENAI_API_KEY"] = previous


def test_register_credential_rejects_whitespace_only_secret() -> None:
    """Whitespace-only bootstrap transport is an empty secret, not a stored newline."""
    with pytest.raises(ValueError, match="empty credential"):
        register_credential("OPENAI_API_KEY", "\n")
    assert get_credential("OPENAI_API_KEY") is None


def test_register_credential_cli_from_env_rejects_whitespace_only() -> None:
    """``--from-env`` of a newline-only mounted secret must not persist."""
    previous = os.environ.get("OPENAI_API_KEY")
    os.environ["OPENAI_API_KEY"] = "  \n"
    try:
        with pytest.raises(SystemExit):
            _register_credential_command(["--name", "OPENAI_API_KEY", "--from-env", "OPENAI_API_KEY"])
        assert get_credential("OPENAI_API_KEY") is None
    finally:
        if previous is None:
            os.environ.pop("OPENAI_API_KEY", None)
        else:
            os.environ["OPENAI_API_KEY"] = previous


def test_get_credential_strips_already_persisted_newline() -> None:
    """A secret stored before write-path strip must still authorize upstream."""
    get_backend().set("OPENAI_API_KEY", "sk-already-persisted\n")
    assert get_credential("OPENAI_API_KEY") == "sk-already-persisted"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
