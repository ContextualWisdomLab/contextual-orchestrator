"""Behavioural coverage for the package command-line entrypoint."""

from __future__ import annotations

import io
import json
from pathlib import Path
import runpy
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import contextual_orchestrator.__main__ as cli  # noqa: E402


class _FakeOrchestrator:
    """Minimal CLI-facing orchestrator that records requested operations."""

    instances: list["_FakeOrchestrator"] = []

    def __init__(self, agents, **kwargs) -> None:
        self.agents = agents
        self.kwargs = kwargs
        self.complete_calls: list[tuple[list[dict], str]] = []
        self.eval_calls: list[tuple[list[str], str]] = []
        type(self).instances.append(self)

    def complete(self, messages: list[dict], mode: str = "auto") -> dict:
        self.complete_calls.append((messages, mode))
        return {"answer": "cli-answer", "mode": mode}

    def compare_to_baseline(self, prompts: list[str], mode: str = "auto") -> dict:
        self.eval_calls.append((prompts, mode))
        return {"prompts": prompts, "mode": mode, "winner": "orchestrator"}


def _patch_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeOrchestrator.instances.clear()
    monkeypatch.setattr(cli, "ModelClient", lambda **kwargs: {"client_kwargs": kwargs})
    monkeypatch.setattr(cli, "load_agents", lambda path: [{"loaded_from": path}])
    monkeypatch.setattr(cli, "TaskOrchestrator", _FakeOrchestrator)


def test_register_credential_reads_stdin_and_reports_only_name(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Bootstrap stdin transport stores the value without echoing the secret."""
    captured: list[tuple[str, str]] = []
    monkeypatch.setattr(cli, "register_credential", lambda name, value: captured.append((name, value)))
    monkeypatch.setattr(sys, "stdin", io.StringIO("super-secret\n"))
    monkeypatch.setattr(sys, "argv", ["contextual-orchestrator", "register-credential", "--name", "NVIDIA_NIM_API_KEY", "--value-stdin"])

    cli.main()

    assert captured == [("NVIDIA_NIM_API_KEY", "super-secret")]
    output = json.loads(capsys.readouterr().out)
    assert output == {"registered": "NVIDIA_NIM_API_KEY", "backend": "kv"}
    assert "super-secret" not in repr(output)


def test_register_credential_reads_named_bootstrap_environment(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Explicit environment bootstrap transport resolves only the named variable."""
    captured: list[tuple[str, str]] = []
    monkeypatch.setattr(cli, "register_credential", lambda name, value: captured.append((name, value)))
    monkeypatch.setenv("BOOTSTRAP_SECRET", "from-env-secret")
    monkeypatch.setattr(
        sys,
        "argv",
        ["contextual-orchestrator", "register-credential", "--name", "provider_key", "--from-env", "BOOTSTRAP_SECRET"],
    )

    cli.main()

    assert captured == [("provider_key", "from-env-secret")]
    assert json.loads(capsys.readouterr().out)["registered"] == "provider_key"


def test_register_credential_rejects_missing_environment_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bootstrap fails closed when the requested transport variable is absent."""
    monkeypatch.delenv("MISSING_BOOTSTRAP_SECRET", raising=False)
    monkeypatch.setattr(
        sys,
        "argv",
        ["contextual-orchestrator", "register-credential", "--name", "provider_key", "--from-env", "MISSING_BOOTSTRAP_SECRET"],
    )
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2


def test_register_credential_rejects_empty_value(monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty stdin secret is rejected before it reaches the credential backend."""
    monkeypatch.setattr(sys, "stdin", io.StringIO(" \n"))
    monkeypatch.setattr(sys, "argv", ["contextual-orchestrator", "register-credential", "--name", "provider_key"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2


def test_prompt_mode_wires_runtime_options_and_prints_completion(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """CLI prompt mode carries routing, storage, TLS, budget, and cache settings."""
    _patch_runtime(monkeypatch)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "contextual-orchestrator",
            "explain the result",
            "--agents",
            "agents.json",
            "--state-db",
            "runs.sqlite",
            "--agents-db",
            "agents.sqlite",
            "--mode",
            "route",
            "--provider-ca-bundle",
            "corp-ca.pem",
            "--insecure-skip-tls-verify",
            "--budget-max-output-tokens",
            "100",
            "--budget-max-cost-usd",
            "2.5",
            "--cache-ttl",
            "4.0",
        ],
    )

    cli.main()

    instance = _FakeOrchestrator.instances[-1]
    assert instance.agents == [{"loaded_from": "agents.json"}]
    assert instance.kwargs["state_db"] == "runs.sqlite"
    assert instance.kwargs["agents_db"] == "agents.sqlite"
    assert instance.kwargs["budget_max_output_tokens"] == 100
    assert instance.kwargs["budget_max_cost_usd"] == 2.5
    assert instance.kwargs["cache_ttl"] == 4.0
    assert instance.kwargs["client"] == {"client_kwargs": {"ca_bundle": "corp-ca.pem", "verify_tls": False}}
    assert instance.complete_calls == [([{"role": "user", "content": "explain the result"}], "route")]
    assert json.loads(capsys.readouterr().out) == {"answer": "cli-answer", "mode": "route"}


def test_eval_mode_prints_comparable_baseline_report(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Evaluation mode routes all supplied prompts through baseline comparison."""
    _patch_runtime(monkeypatch)
    monkeypatch.setattr(
        sys,
        "argv",
        ["contextual-orchestrator", "--mode", "conduct", "--eval", "prompt one", "prompt two"],
    )

    cli.main()

    instance = _FakeOrchestrator.instances[-1]
    assert instance.eval_calls == [(["prompt one", "prompt two"], "conduct")]
    report = json.loads(capsys.readouterr().out)
    assert report["winner"] == "orchestrator"
    assert report["prompts"] == ["prompt one", "prompt two"]


def test_serve_requires_an_authentication_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Server mode fails closed when no shared or split token is configured."""
    _patch_runtime(monkeypatch)
    monkeypatch.delenv("CONTEXTUAL_ORCHESTRATOR_TOKEN", raising=False)
    monkeypatch.delenv("CONTEXTUAL_ORCHESTRATOR_ADMIN_TOKEN", raising=False)
    monkeypatch.delenv("CONTEXTUAL_ORCHESTRATOR_INFERENCE_TOKEN", raising=False)
    monkeypatch.setattr(sys, "argv", ["contextual-orchestrator", "--serve"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2


def test_serve_rejects_incomplete_split_token_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Split-scope authentication requires both administrator and inference tokens."""
    _patch_runtime(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["contextual-orchestrator", "--serve", "--admin-token", "admin-only"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2


def test_serve_wires_security_and_clearfolio_options(monkeypatch: pytest.MonkeyPatch) -> None:
    """Authenticated server mode forwards its explicit network and security posture."""
    _patch_runtime(monkeypatch)
    captured: dict = {}

    def fake_serve(orchestrator, **kwargs) -> None:
        captured["orchestrator"] = orchestrator
        captured.update(kwargs)

    monkeypatch.setattr(cli, "serve", fake_serve)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "contextual-orchestrator",
            "--serve",
            "--host",
            "0.0.0.0",
            "--port",
            "9010",
            "--admin-token",
            "admin-token",
            "--inference-token",
            "inference-token",
            "--allow-public-bind",
            "--expose-trace-by-default",
            "--clearfolio-url",
            "https://clearfolio.example",
            "--insecure-disable-auth",
        ],
    )

    cli.main()

    security = captured["security"]
    assert captured["host"] == "0.0.0.0"
    assert captured["port"] == 9010
    assert captured["clearfolio_url"] == "https://clearfolio.example"
    assert security.auth_token == ""
    assert security.admin_token == "admin-token"
    assert security.inference_token == "inference-token"
    assert security.allow_public_bind is True
    assert security.expose_trace_by_default is True


def test_serve_accepts_legacy_shared_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """The shared-token compatibility path remains accepted for authenticated serving."""
    _patch_runtime(monkeypatch)
    calls: list[dict] = []
    monkeypatch.setattr(cli, "serve", lambda orchestrator, **kwargs: calls.append(kwargs))
    monkeypatch.setattr(sys, "argv", ["contextual-orchestrator", "--serve", "--auth-token", "shared-token"])

    cli.main()

    assert calls[0]["security"].auth_token == "shared-token"


def test_missing_prompt_is_a_usage_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-server execution requires a prompt when evaluation mode is absent."""
    _patch_runtime(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["contextual-orchestrator"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2


def test_module_execution_runs_real_mock_cli_path(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """Executing the package module as ``__main__`` reaches the documented mock default."""
    monkeypatch.setattr(sys, "argv", ["contextual-orchestrator", "hello from module execution", "--mode", "route"])
    runpy.run_module("contextual_orchestrator.__main__", run_name="__main__")
    output = json.loads(capsys.readouterr().out)
    assert isinstance(output.get("answer"), str)
    assert output["answer"]
