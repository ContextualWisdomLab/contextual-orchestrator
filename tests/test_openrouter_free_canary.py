"""Contracts for the bounded OpenRouter free-model canary."""

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import threading
import pytest

from contextual_orchestrator.credentials import InMemoryCredentialBackend, set_backend
from contextual_orchestrator.model_discovery import DiscoveredModel
from contextual_orchestrator.openrouter_canary import (
    OpenRouterCanaryError,
    OpenRouterCanaryLimits,
    prune_expired_openrouter_canary_evidence,
    run_openrouter_free_canary,
)
from contextual_orchestrator import __main__ as cli


def _model(
    model_id: str,
    *,
    prompt=0.0,
    completion=0.0,
    is_free=True,
    input_modalities=(),
) -> DiscoveredModel:
    return DiscoveredModel(
        "openrouter",
        model_id,
        "OPENROUTER_API_KEY",
        "https://openrouter.ai/api/v1",
        "Bearer",
        capabilities=("chat",),
        prompt_price_per_1k=prompt,
        completion_price_per_1k=completion,
        is_free=is_free,
        input_modalities=input_modalities,
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
                _model("paid-unit", is_free=False),
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


def test_live_fails_before_transport_when_evidence_path_is_unwritable(
    tmp_path: Path, monkeypatch
) -> None:
    backend = InMemoryCredentialBackend()
    backend.set("OPENROUTER_API_KEY", "secret")
    set_backend(backend)
    monkeypatch.setattr(
        "contextual_orchestrator.openrouter_canary.tempfile.mkstemp",
        lambda **_kwargs: (_ for _ in ()).throw(PermissionError("denied")),
    )
    try:
        with pytest.raises(OpenRouterCanaryError, match="not writable"):
            run_openrouter_free_canary(
                live=True,
                limits=OpenRouterCanaryLimits(1, 8, 3, 7),
                evidence_output=tmp_path / "evidence.json",
                discover=lambda *_a, **_k: pytest.fail("discovery after bad output"),
                client_factory=lambda **_k: pytest.fail("transport"),
            )
    finally:
        set_backend(None)


def test_expired_evidence_cleanup_never_contacts_provider(tmp_path: Path) -> None:
    output = tmp_path / "evidence.json"
    output.write_text(
        '{"schema_version":1,"provider":"openrouter","mode":"live","expires_at":100}\n'
    )
    assert prune_expired_openrouter_canary_evidence(output, now=lambda: 100) is True
    assert not output.exists()
    assert prune_expired_openrouter_canary_evidence(output, now=lambda: 101) is False

    output.write_text(
        '{"schema_version":1,"provider":"openrouter","mode":"live","expires_at":200}\n'
    )
    assert prune_expired_openrouter_canary_evidence(output, now=lambda: 199) is False
    assert output.exists()


def test_cleanup_rejects_unrelated_json_and_special_paths(tmp_path: Path) -> None:
    unrelated = tmp_path / "unrelated.json"
    unrelated.write_text('{"expires_at": 1}\n')
    with pytest.raises(OpenRouterCanaryError, match="not OpenRouter"):
        prune_expired_openrouter_canary_evidence(unrelated, now=lambda: 2)
    assert unrelated.exists()

    symlink = tmp_path / "evidence-link.json"
    symlink.symlink_to(unrelated)
    with pytest.raises(OpenRouterCanaryError, match="regular file"):
        prune_expired_openrouter_canary_evidence(symlink, now=lambda: 2)
    assert unrelated.exists()


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
        with pytest.raises(OpenRouterCanaryError, match="zero-price"):
            run_openrouter_free_canary(
                live=False,
                discover=lambda *_a, **_k: [_model("paid-verdict", is_free=False)],
            )
    finally:
        set_backend(None)


def test_canary_reconciles_duplicate_prices_and_skips_non_text_input() -> None:
    backend = InMemoryCredentialBackend()
    backend.set("OPENROUTER_API_KEY", "secret")
    set_backend(backend)
    try:
        result = run_openrouter_free_canary(
            live=False,
            discover=lambda *_a, **_k: [
                _model("a-conflict"),
                _model("a-conflict", prompt=0.01),
                _model("b-image", input_modalities=("image",)),
                _model("c-text", input_modalities=("text",)),
            ],
            client_factory=lambda **_k: pytest.fail("completion transport"),
        )
    finally:
        set_backend(None)
    assert result["model_id"] == "c-text"


def test_live_preflights_output_and_removes_expired_evidence(tmp_path: Path) -> None:
    backend = InMemoryCredentialBackend()
    backend.set("OPENROUTER_API_KEY", "secret")
    set_backend(backend)
    expired = tmp_path / "expired.json"
    expired.write_text(
        '{"schema_version":1,"provider":"openrouter","mode":"live","expires_at":99}',
        encoding="utf-8",
    )
    seen = {}

    class Client:
        def __init__(self, **_kwargs):
            seen["outcome_before_transport"] = json.loads(
                expired.read_text(encoding="utf-8")
            )["outcome"]

        def chat(self, _agent, _messages):
            return "OK"

    try:
        run_openrouter_free_canary(
            live=True,
            limits=OpenRouterCanaryLimits(1, 8, 3, 7),
            evidence_output=expired,
            discover=lambda *_a, **_k: [_model("current-free")],
            client_factory=Client,
            now=lambda: 100,
        )
        with pytest.raises(OpenRouterCanaryError, match="regular file"):
            run_openrouter_free_canary(
                live=True,
                limits=OpenRouterCanaryLimits(1, 8, 3, 7),
                evidence_output=tmp_path,
                discover=lambda *_a, **_k: pytest.fail("discovery transport"),
                client_factory=lambda **_k: pytest.fail("completion transport"),
                now=lambda: 100,
            )
    finally:
        set_backend(None)
    assert seen["outcome_before_transport"] == "pending"
    assert expired.stat().st_mode & 0o777 == 0o600


def test_live_persists_attempt_and_validates_response(tmp_path: Path) -> None:
    backend = InMemoryCredentialBackend()
    backend.set("OPENROUTER_API_KEY", "secret")
    set_backend(backend)
    output = tmp_path / "evidence.json"

    class Client:
        def __init__(self, **_kwargs):
            pass

        def chat(self, _agent, _messages):
            document = output.read_text(encoding="utf-8")
            assert '"outcome": "pending"' in document
            assert '"request_count": 1' in document
            return "not ok"

    try:
        with pytest.raises(OpenRouterCanaryError, match="invalid response"):
            run_openrouter_free_canary(
                live=True,
                limits=OpenRouterCanaryLimits(1, 8, 3, 7),
                evidence_output=output,
                discover=lambda *_a, **_k: [_model("current-free")],
                client_factory=Client,
                now=iter((100, 200)).__next__,
            )
    finally:
        set_backend(None)
    assert '"outcome": "invalid_response"' in output.read_text(encoding="utf-8")
    assert '"discovered_at": 200' in output.read_text(encoding="utf-8")


def test_live_serializes_one_evidence_path_across_invocations(tmp_path: Path) -> None:
    backend = InMemoryCredentialBackend()
    backend.set("OPENROUTER_API_KEY", "secret")
    set_backend(backend)
    output = tmp_path / "evidence.json"
    entered = threading.Event()
    release = threading.Event()
    calls = []

    class Client:
        def __init__(self, **_kwargs):
            pass

        def chat(self, _agent, _messages):
            calls.append("transport")
            entered.set()
            assert release.wait(timeout=2)
            return "OK"

    def invoke():
        return run_openrouter_free_canary(
            live=True,
            limits=OpenRouterCanaryLimits(1, 8, 3, 7),
            evidence_output=output,
            discover=lambda *_a, **_k: [_model("current-free")],
            client_factory=Client,
            now=lambda: 100,
        )

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(invoke)
            assert entered.wait(timeout=2)
            second = pool.submit(invoke)
            release.set()
            assert first.result()["outcome"] == "completed"
            with pytest.raises(OpenRouterCanaryError, match="already exists"):
                second.result()
    finally:
        set_backend(None)
    assert calls == ["transport"]


def test_live_rejects_fifo_before_discovery_or_completion_transport(
    tmp_path: Path,
) -> None:
    backend = InMemoryCredentialBackend()
    backend.set("OPENROUTER_API_KEY", "secret")
    set_backend(backend)
    fifo = tmp_path / "evidence.fifo"
    fifo_path = str(fifo)
    import os

    os.mkfifo(fifo_path)
    try:
        with pytest.raises(OpenRouterCanaryError, match="regular file"):
            run_openrouter_free_canary(
                live=True,
                limits=OpenRouterCanaryLimits(1, 8, 3, 7),
                evidence_output=fifo,
                discover=lambda *_a, **_k: pytest.fail("discovery transport"),
                client_factory=lambda **_k: pytest.fail("completion transport"),
                now=lambda: 100,
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


def test_cli_cleanup_and_contract_failures_have_controlled_exit(
    monkeypatch, capsys
) -> None:
    monkeypatch.setattr(
        cli, "prune_expired_openrouter_canary_evidence", lambda _path: True
    )
    cli.main(["openrouter-free-canary", "--prune-expired-evidence", "evidence.json"])
    assert '"expired_evidence_removed": true' in capsys.readouterr().out

    monkeypatch.setattr(
        cli,
        "run_openrouter_free_canary",
        lambda **_kwargs: (_ for _ in ()).throw(OpenRouterCanaryError("safe failure")),
    )
    with pytest.raises(SystemExit) as failure:
        cli.main(["openrouter-free-canary"])
    captured = capsys.readouterr()
    assert failure.value.code == 1
    assert captured.err == (
        '{"error": {"code": "openrouter_canary_failed", "message": "safe failure"}}\n'
    )
    assert "Traceback" not in captured.err


def test_root_help_lists_canary_command(capsys) -> None:
    with pytest.raises(SystemExit) as help_exit:
        cli.main(["--help"])
    assert help_exit.value.code == 0
    assert "openrouter-free-canary" in capsys.readouterr().out
