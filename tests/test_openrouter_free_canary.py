"""Contracts for the bounded OpenRouter free-model canary."""

from pathlib import Path
import pytest

from contextual_orchestrator.credentials import InMemoryCredentialBackend, set_backend
from contextual_orchestrator.model_discovery import DiscoveredModel
from contextual_orchestrator.openrouter_canary import (
    OpenRouterCanaryError,
    OpenRouterCanaryLimits,
    run_openrouter_free_canary,
)
from contextual_orchestrator import __main__ as cli


def _model(model_id: str, *, prompt=0.0, completion=0.0) -> DiscoveredModel:
    return DiscoveredModel(
        "openrouter",
        model_id,
        "OPENROUTER_API_KEY",
        "https://openrouter.ai/api/v1",
        "Bearer",
        capabilities=("chat",),
        prompt_price_per_1k=prompt,
        completion_price_per_1k=completion,
        is_free=True,
    )


def test_dry_run_selects_current_zero_price_without_transport() -> None:
    backend = InMemoryCredentialBackend()
    backend.set("OPENROUTER_API_KEY", "secret")
    set_backend(backend)
    try:
        result = run_openrouter_free_canary(
            live=False,
            discover=lambda *_a, **_k: [
                _model("unknown", prompt=None),
                _model("z-free"),
                _model("a-free"),
            ],
            client_factory=lambda **_k: pytest.fail("transport"),
            now=lambda: 123,
        )
    finally:
        set_backend(None)
    assert result["model_id"] == "a-free" and result["request_count"] == 0
    assert "secret" not in str(result)


def test_live_request_is_capped_and_writes_prompt_free_evidence(tmp_path: Path) -> None:
    backend = InMemoryCredentialBackend()
    backend.set("OPENROUTER_API_KEY", "secret")
    set_backend(backend)
    seen = {}

    class Client:
        def __init__(self, **kwargs):
            seen["limits"] = kwargs

        def chat(self, agent, messages):
            seen["messages"] = messages
            return "OK"

    output = tmp_path / "evidence.json"
    try:
        result = run_openrouter_free_canary(
            live=True,
            limits=OpenRouterCanaryLimits(1, 8, 3, 7),
            evidence_output=output,
            discover=lambda *_a, **_k: [_model("current-free")],
            client_factory=Client,
            now=lambda: 100,
        )
    finally:
        set_backend(None)
    assert seen["limits"] == {
        "timeout": 3,
        "max_output_tokens": 8,
        "max_retries": 0,
        "temperature": 0.0,
    }
    assert result["request_count"] == 1 and result["expires_at"] == 604900
    assert "Reply OK" not in output.read_text() and "secret" not in output.read_text()


def test_canary_fails_closed_on_missing_credential_or_price() -> None:
    set_backend(InMemoryCredentialBackend())
    try:
        with pytest.raises(OpenRouterCanaryError, match="KV registry"):
            run_openrouter_free_canary(live=False, discover=lambda *_a, **_k: [])
        backend = InMemoryCredentialBackend()
        backend.set("OPENROUTER_API_KEY", "secret")
        set_backend(backend)
        with pytest.raises(OpenRouterCanaryError, match="zero-price"):
            run_openrouter_free_canary(
                live=False,
                discover=lambda *_a, **_k: [_model("ambiguous", completion=None)],
            )
    finally:
        set_backend(None)


def test_cli_defaults_to_dry_run_and_live_requires_every_bound(
    monkeypatch, capsys
) -> None:
    seen = {}
    monkeypatch.setattr(
        cli,
        "run_openrouter_free_canary",
        lambda **kwargs: seen.update(kwargs) or {"mode": "dry_run"},
    )
    cli.main(["openrouter-free-canary"])
    assert seen["live"] is False and seen["limits"] is None
    assert '"mode": "dry_run"' in capsys.readouterr().out
    with pytest.raises(SystemExit):
        cli.main(["openrouter-free-canary", "--live", "--max-requests", "1"])
