"""CLI server-auth resolution stays explicit or KV-backed."""

from __future__ import annotations

import sys
import types
from io import StringIO
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator.__main__ import _resolve_auth_token, main
from contextual_orchestrator.credentials import (
    InMemoryCredentialBackend,
    set_backend,
)


def test_auth_token_resolution_prefers_explicit_then_kv() -> None:
    backend = InMemoryCredentialBackend()
    backend.set("gateway_token", "from-kv")
    set_backend(backend)
    try:
        assert _resolve_auth_token("explicit", "gateway_token") == "explicit"
        assert _resolve_auth_token("", "gateway_token") == "from-kv"
        try:
            _resolve_auth_token("", "missing_token")
        except ValueError as exc:
            assert "not configured" in str(exc)
        else:  # pragma: no cover
            raise AssertionError("missing auth credential was accepted")
    finally:
        set_backend(None)


def test_partial_split_tokens_fail_before_kv_lookup() -> None:
    stderr = StringIO()
    with (
        patch.object(sys, "argv", ["contextual-orchestrator", "--serve", "--admin-token", "admin"]),
        patch.object(sys, "stderr", stderr),
        patch(
            "contextual_orchestrator.__main__.get_credential",
            side_effect=AssertionError("KV lookup was premature"),
        ),
    ):
        try:
            main()
        except SystemExit as exc:
            assert exc.code == 2
            assert "--admin-token-key" in stderr.getvalue()
            assert "--inference-token-key" in stderr.getvalue()
        else:  # pragma: no cover
            raise AssertionError("partial split token mode must be rejected")


def test_key_only_split_tokens_select_split_mode() -> None:
    backend = InMemoryCredentialBackend()
    backend.set("admin_key", "admin-from-kv")
    backend.set("inference_key", "inference-from-kv")
    set_backend(backend)
    try:
        with patch.object(
            sys,
            "argv",
            [
                "contextual-orchestrator",
                "--serve",
                "--admin-token-key",
                "admin_key",
                "--inference-token-key",
                "inference_key",
            ],
        ), patch("contextual_orchestrator.__main__.serve") as serve:
            main()
        security = serve.call_args.kwargs["security"]
        assert security.auth_token == ""
        assert security.admin_token == "admin-from-kv"
        assert security.inference_token == "inference-from-kv"
    finally:
        set_backend(None)


def test_invalid_local_provider_options_fail_at_parser_boundary() -> None:
    invalid_options = (
        (["--local-concurrency", "0"], "positive integer"),
        (["--local-concurrency", "-1"], "positive integer"),
        (["--local-concurrency", "65"], "1..64"),
        (["--max-concurrent-runs", "0"], "positive integer"),
        (["--max-concurrent-runs", "65"], "1..64"),
        (["--chat-template-args", "[]"], "JSON object"),
        (["--chat-template-args", "null"], "JSON object"),
        (["--chat-template-args", "{"], "valid JSON object"),
    )

    for options, expected_message in invalid_options:
        stderr = StringIO()
        with (
            patch.object(sys, "argv", ["contextual-orchestrator", *options]),
            patch.object(sys, "stderr", stderr),
            patch(
                "contextual_orchestrator.__main__.ModelClient",
                side_effect=AssertionError("invalid CLI input reached ModelClient"),
            ),
        ):
            try:
                main()
            except SystemExit as exc:
                assert exc.code == 2
                assert expected_message in stderr.getvalue()
            else:  # pragma: no cover
                raise AssertionError("invalid local provider option was accepted")


def test_server_concurrency_is_explicit_and_bounded() -> None:
    with (
        patch.object(
            sys,
            "argv",
            [
                "contextual-orchestrator",
                "--serve",
                "--auth-token",
                "token",
                "--local-concurrency",
                "16",
                "--max-concurrent-runs",
                "16",
            ],
        ),
        patch("contextual_orchestrator.__main__.load_agents", return_value=[]),
        patch("contextual_orchestrator.__main__.ModelClient"),
        patch("contextual_orchestrator.__main__.TaskOrchestrator"),
        patch("contextual_orchestrator.__main__.serve") as serve,
    ):
        main()
    assert serve.call_args.kwargs["security"].max_concurrent_runs == 16


def test_local_http_session_cookie_requires_explicit_opt_in() -> None:
    with (
        patch.object(sys, "argv", ["contextual-orchestrator", "--serve", "--auth-token", "token", "--insecure-admin-session-cookie"]),
        patch("contextual_orchestrator.__main__.load_agents", return_value=[]),
        patch("contextual_orchestrator.__main__.ModelClient"),
        patch("contextual_orchestrator.__main__.TaskOrchestrator"),
        patch("contextual_orchestrator.__main__.serve") as serve,
    ):
        main()
    assert serve.call_args.kwargs["security"].admin_session_secure_cookie is False


def test_sampling_temperature_uses_descriptive_name_and_legacy_alias() -> None:
    for option in ("--sampling-temperature", "--temperature"):
        with (
            patch.object(
                sys,
                "argv",
                ["contextual-orchestrator", "--serve", "--auth-token", "token", option, "0.7"],
            ),
            patch("contextual_orchestrator.__main__.load_agents", return_value=[]),
            patch("contextual_orchestrator.__main__.ModelClient") as model_client,
            patch("contextual_orchestrator.__main__.TaskOrchestrator"),
            patch("contextual_orchestrator.__main__.serve"),
        ):
            main()
        assert model_client.call_args.kwargs["temperature"] == 0.7


def test_fast_mlsirm_preflight_reports_missing_transitive_dependency() -> None:
    stderr = StringIO()
    real_import = __import__

    def import_without_fast(name: str, *args, **kwargs):
        if name == "fast_mlsirm":
            raise ModuleNotFoundError("No module named 'numpy'", name="numpy")
        return real_import(name, *args, **kwargs)

    with (
        patch.object(sys, "argv", ["contextual-orchestrator", "check-fast-mlsirm"]),
        patch.object(sys, "stdout", stderr),
        patch("builtins.__import__", side_effect=import_without_fast),
    ):
        try:
            main()
        except SystemExit as exc:
            assert exc.code == 1
        else:  # pragma: no cover
            raise AssertionError("missing judge dependency must fail closed")
    assert '"missing_module": "numpy"' in stderr.getvalue()


def test_fast_mlsirm_preflight_accepts_the_versioned_contract() -> None:
    fake_package = types.ModuleType("fast_mlsirm")
    fake_package.__version__ = "test"
    fake_package.CONTEXTUAL_ORCHESTRATOR_CONTRACT_V1 = "contextual-orchestrator-contract-v1"
    fake_package.ContextualOrchestratorJudge = type("ContextualOrchestratorJudge", (), {})
    fake_package.JudgeCriterion = type("JudgeCriterion", (), {})
    fake_package.JudgeFormatError = type("JudgeFormatError", (Exception,), {})
    stdout = StringIO()
    with (
        patch.dict(sys.modules, {"fast_mlsirm": fake_package}),
        patch.object(sys, "argv", ["contextual-orchestrator", "check-fast-mlsirm"]),
        patch.object(sys, "stdout", stdout),
    ):
        main()
    assert '"available": true' in stdout.getvalue()
    assert '"contextual_contract": true' in stdout.getvalue()


if __name__ == "__main__":
    test_auth_token_resolution_prefers_explicit_then_kv()
    test_partial_split_tokens_fail_before_kv_lookup()
    test_key_only_split_tokens_select_split_mode()
    test_invalid_local_provider_options_fail_at_parser_boundary()
    test_sampling_temperature_uses_descriptive_name_and_legacy_alias()
    print("ok")
