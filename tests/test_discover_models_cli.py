"""`python -m contextual_orchestrator discover-models` CLI subcommand."""

from __future__ import annotations

import json
import os
import sys
import urllib.parse
from io import StringIO
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator.__main__ import main  # noqa: E402
from contextual_orchestrator.credentials import (  # noqa: E402
    InMemoryCredentialBackend,
    get_credential,
    register_credential,
    set_backend,
)


class _Response:
    def __init__(self, payload: dict) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return self._body


def test_free_only_help_rejects_name_inference() -> None:
    """CLI guidance matches the fail-closed structured-price contract."""
    stdout = StringIO()
    with (
        patch.object(sys, "argv", ["contextual-orchestrator", "discover-models", "--help"]),
        patch.object(sys, "stdout", stdout),
    ):
        try:
            main()
        except SystemExit as exc:
            assert exc.code == 0
    help_text = " ".join(stdout.getvalue().split())
    assert "structured provider/catalog price metadata" in help_text
    assert "-free/:free" not in help_text


def test_discover_models_with_no_credentials_reports_zero_and_succeeds() -> None:
    set_backend(InMemoryCredentialBackend())
    stdout = StringIO()
    try:
        with (
            patch.object(sys, "argv", ["contextual-orchestrator", "discover-models"]),
            patch.object(sys, "stdout", stdout),
        ):
            main()  # must not raise SystemExit
    finally:
        set_backend(None)
    report = json.loads(stdout.getvalue())
    assert report == {
        "discovered_count": 0,
        "priced_count": 0,
        "providers_with_errors": [],
        "enabled_agent_ids": [],
        "free_tier_count": 0,
        "free_data_privacy": {"supported": 0, "unsupported": 0, "unknown": 0},
        "models": [],
    }


def test_discover_models_reports_invalid_gateway_configuration_without_traceback() -> None:
    """Invalid gateway configuration exits through argparse's actionable error path."""
    stderr = StringIO()
    environment = {
        "LLM_GATEWAY_API_URL": "http://gateway.example/v1",
        "CONTEXTUAL_ORCHESTRATOR_ALLOWED_PROVIDER_HOSTS": "gateway.example",
    }
    with (
        patch.dict(os.environ, environment, clear=True),
        patch.object(sys, "argv", ["contextual-orchestrator", "discover-models"]),
        patch.object(sys, "stderr", stderr),
    ):
        try:
            main()
        except SystemExit as exc:
            assert exc.code == 2
        else:
            raise AssertionError("invalid gateway configuration must exit")

    assert "error:" in stderr.getvalue()
    assert "Traceback" not in stderr.getvalue()


def test_discover_models_reports_models_found_over_a_registered_credential() -> None:
    set_backend(InMemoryCredentialBackend())
    register_credential("OPENAI_API_KEY", "sk-live")
    stdout = StringIO()

    def urlopen(request, timeout=None):
        if urllib.parse.urlsplit(request.full_url).hostname == "api.openai.com":
            return _Response({"data": [{"id": "gpt-5.5"}]})
        return _Response({"data": []})

    try:
        with (
            patch.object(sys, "argv", ["contextual-orchestrator", "discover-models"]),
            patch.object(sys, "stdout", stdout),
            patch("contextual_orchestrator.model_discovery.urllib.request.urlopen", side_effect=urlopen),
        ):
            main()
    finally:
        set_backend(None)
    report = json.loads(stdout.getvalue())
    assert report["discovered_count"] == 1
    assert report["models"] == [
        {
            "provider": "openai", "model": "gpt-5.5", "agent_id": "openai_gpt_5_5",
            "is_free": False,
            "data_privacy": {
                "zero_data_retention": "unknown",
                "no_training": "unknown",
                "no_prompt_retention": "unknown",
                "policy_sources": [],
            },
        }
    ]


def test_discover_models_bootstraps_allowlisted_openai_gateway_from_environment() -> None:
    """A one-shot env secret enters KV before full paid/free chat discovery."""
    set_backend(InMemoryCredentialBackend())
    stdout = StringIO()
    environment = {
        "LLM_GATEWAY_API_URL": "https://gateway.example/v1",
        "LLM_GATEWAY_URL": "https://gateway.example/v1/",
        "LLM_GATEWAY_API_KEY": "  gateway-secret\n",
        "CONTEXTUAL_ORCHESTRATOR_ALLOWED_PROVIDER_HOSTS": "gateway.example",
    }

    def fetch(url, **kwargs):
        assert kwargs["api_key"] == "gateway-secret"
        if url.endswith("/model/info"):
            return {
                "data": [
                    {
                        "model_name": "gpt-5.6-sol",
                        "model_info": {
                            "mode": "chat",
                            "input_cost_per_token": 0.000005,
                            "output_cost_per_token": 0.00003,
                        },
                    },
                    {
                        "model_name": "community/free-chat",
                        "model_info": {
                            "mode": "chat",
                            "input_cost_per_token": 0,
                            "output_cost_per_token": 0,
                        },
                    },
                    {
                        "model_name": "text-embedding-3-large",
                        "model_info": {
                            "mode": "embedding",
                            "input_cost_per_token": 0.00000013,
                            "output_cost_per_token": 0,
                        },
                    },
                ]
            }
        assert url == "https://gateway.example/v1/models"
        return {
            "data": [
                {"id": "gpt-5.6-sol"},
                {
                    "id": "community/free-chat",
                    "pricing": {"prompt": "0", "completion": "0"},
                },
                {"id": "text-embedding-3-large"},
            ]
        }

    try:
        with (
            patch.dict(os.environ, environment, clear=True),
            patch.object(sys, "argv", ["contextual-orchestrator", "discover-models"]),
            patch.object(sys, "stdout", stdout),
            patch(
                "contextual_orchestrator.model_discovery._fetch_configured_gateway_json",
                side_effect=fetch,
            ),
        ):
            main()
            assert get_credential("LLM_GATEWAY_API_KEY") == "gateway-secret"
    finally:
        set_backend(None)

    report = json.loads(stdout.getvalue())
    assert report["discovered_count"] == 3
    assert report["free_tier_count"] == 1
    assert report["priced_count"] == 2
    assert [row["model"] for row in report["models"]] == [
        "gpt-5.6-sol",
        "community/free-chat",
        "text-embedding-3-large",
    ]


def test_configured_gateway_requires_explicit_host_allowlist() -> None:
    """Bootstrap URL configuration cannot create an unrestricted SSRF target."""
    set_backend(InMemoryCredentialBackend())
    try:
        stderr = StringIO()
        with (
            patch.dict(
                os.environ,
                {
                    "LLM_GATEWAY_URL": "https://gateway.example/v1",
                    "LLM_GATEWAY_API_KEY": "secret",
                },
                clear=True,
            ),
            patch.object(sys, "argv", ["contextual-orchestrator", "discover-models"]),
            patch.object(sys, "stderr", stderr),
        ):
            try:
                main()
            except SystemExit as exc:
                assert exc.code == 2
            else:  # pragma: no cover
                raise AssertionError("unallowlisted gateway must fail")
        assert "allowlist" in stderr.getvalue()
    finally:
        set_backend(None)


def test_discover_models_persists_to_agents_db(tmp_path) -> None:
    from contextual_orchestrator import TaskOrchestrator
    from contextual_orchestrator.orchestrator import ModelAgent

    set_backend(InMemoryCredentialBackend())
    register_credential("OPENAI_API_KEY", "sk-live")
    db_path = str(tmp_path / "pool.db")
    stdout = StringIO()

    def urlopen(request, timeout=None):
        if urllib.parse.urlsplit(request.full_url).hostname == "api.openai.com":
            return _Response({"data": [{"id": "gpt-5.5"}]})
        return _Response({"data": []})

    try:
        with (
            patch.object(sys, "argv", ["contextual-orchestrator", "discover-models", "--agents-db", db_path]),
            patch.object(sys, "stdout", stdout),
            patch("contextual_orchestrator.model_discovery.urllib.request.urlopen", side_effect=urlopen),
        ):
            main()
    finally:
        set_backend(None)

    reloaded = TaskOrchestrator([ModelAgent("seed_agent", "seed-model")], agents_db=db_path)
    assert any(agent.id == "openai_gpt_5_5" for agent in reloaded.candidates)


def test_enable_cheapest_requires_agents_db() -> None:
    set_backend(InMemoryCredentialBackend())
    stderr = StringIO()
    try:
        with (
            patch.object(sys, "argv", ["contextual-orchestrator", "discover-models", "--enable-cheapest", "1"]),
            patch.object(sys, "stderr", stderr),
        ):
            try:
                main()
            except SystemExit as exc:
                assert exc.code == 2
            else:  # pragma: no cover
                raise AssertionError("--enable-cheapest without --agents-db must fail")
    finally:
        set_backend(None)
    assert "--agents-db" in stderr.getvalue()


def test_enable_cheapest_activates_the_lowest_priced_discovered_agent(tmp_path) -> None:
    from contextual_orchestrator import TaskOrchestrator
    from contextual_orchestrator.orchestrator import ModelAgent

    set_backend(InMemoryCredentialBackend())
    register_credential("OPENAI_API_KEY", "sk-live")
    register_credential("OPENROUTER_API_KEY", "sk-router")
    db_path = str(tmp_path / "pool.db")
    stdout = StringIO()

    def urlopen(request, timeout=None):
        host = urllib.parse.urlsplit(request.full_url).hostname
        if host == "api.openai.com":
            return _Response({"data": [{"id": "pricey-model", "pricing": {"prompt": "0.00005", "completion": "0.0001"}}]})
        if host == "openrouter.ai":
            return _Response({"data": [{"id": "cheap-model", "pricing": {"prompt": "0.0000001", "completion": "0.0000002"}}]})
        return _Response({"data": []})

    try:
        with (
            patch.object(
                sys,
                "argv",
                ["contextual-orchestrator", "discover-models", "--agents-db", db_path, "--enable-cheapest", "1"],
            ),
            patch.object(sys, "stdout", stdout),
            patch("contextual_orchestrator.model_discovery.urllib.request.urlopen", side_effect=urlopen),
        ):
            main()
    finally:
        set_backend(None)

    report = json.loads(stdout.getvalue())
    assert report["enabled_agent_ids"] == ["openrouter_cheap_model"]

    reloaded = TaskOrchestrator([ModelAgent("seed_agent", "seed-model")], agents_db=db_path)
    by_id = {agent.id: agent for agent in reloaded.candidates}
    assert by_id["openrouter_cheap_model"].disabled is False
    assert by_id["openai_pricey_model"].disabled is True


def test_enable_cheapest_bootstraps_independent_provider_families(tmp_path) -> None:
    """CLI bootstrap must use the provider-diverse selector, not only the cheapest vendor."""
    from contextual_orchestrator import TaskOrchestrator
    from contextual_orchestrator.orchestrator import ModelAgent

    set_backend(InMemoryCredentialBackend())
    register_credential("OPENAI_API_KEY", "sk-openai")
    register_credential("OPENROUTER_API_KEY", "sk-router")
    register_credential("NVIDIA_NIM_API_KEY", "nv-primary")
    db_path = str(tmp_path / "pool.db")
    stdout = StringIO()

    def urlopen(request, timeout=None):
        host = urllib.parse.urlsplit(request.full_url).hostname
        payloads = {
            "api.openai.com": {"data": [{"id": "openai-model", "pricing": {"prompt": "0.001", "completion": "0.001"}}]},
            "openrouter.ai": {"data": [{"id": "router-model", "pricing": {"prompt": "0.000001", "completion": "0.000001"}}]},
            "integrate.api.nvidia.com": {"data": [{"id": "nim-model", "pricing": {"prompt": "0.000002", "completion": "0.000002"}}]},
        }
        return _Response(payloads.get(host, {"data": []}))

    try:
        with (
            patch.object(
                sys,
                "argv",
                ["contextual-orchestrator", "discover-models", "--agents-db", db_path, "--enable-cheapest", "3"],
            ),
            patch.object(sys, "stdout", stdout),
            patch("contextual_orchestrator.model_discovery.urllib.request.urlopen", side_effect=urlopen),
        ):
            main()
    finally:
        set_backend(None)

    report = json.loads(stdout.getvalue())
    assert report["enabled_agent_ids"] == [
        "openrouter_router_model",
        "nvidia_nim_nim_model",
        "openai_openai_model",
    ]
    reloaded = TaskOrchestrator([ModelAgent("seed_agent", "seed-model")], agents_db=db_path)
    enabled = {agent.id for agent in reloaded.candidates if not agent.disabled}
    assert enabled - {"seed_agent"} == set(report["enabled_agent_ids"])
