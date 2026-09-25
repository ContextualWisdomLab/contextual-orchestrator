"""Bytez unfiltered fallback, Experiential key spellings, and OpenCode Go protocol/session contracts.

Every provider response here is a fixture; no test reaches a real provider.
"""

from __future__ import annotations

import os
import urllib.error
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from contextual_orchestrator.credentials import register_credential
from contextual_orchestrator.model_discovery import (
    OPENCODE_GO_MODEL_ENDPOINTS,
    PROVIDER_MODEL_SOURCES,
    ProviderDiscoveryError,
    _parse_openai_compatible,
    bootstrap_credential_value,
    credential_env_names,
    discover_provider_models,
    opencode_go_model_endpoint,
)
from contextual_orchestrator.opencode_headers import (
    OPENCODE_SESSION_HEADER,
    opencode_request_headers,
    opencode_session_id,
)
from contextual_orchestrator.provider_bootstrap import collect_provider_credentials
from contextual_orchestrator.review_gateway import register_review_credentials

SOURCES = {source.provider_name: source for source in PROVIDER_MODEL_SOURCES}
EXPLABS_KV = "EXPERIENTAL_LABS_API_KEY"


class _Response:
    def __init__(self, payload):
        import json

        self._body = json.dumps(payload).encode("utf-8")

    def read(self, *_args):
        body, self._body = self._body, b""
        return body

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def close(self):
        return None


# --- Bytez ---------------------------------------------------------------


def _http_500(url: str) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(url, 500, "Internal Server Error", hdrs=None, fp=None)


def test_bytez_unfiltered_fallback_keeps_only_chat_task_rows() -> None:
    """Both task filters answering 500 must not end discovery when the plain list works."""
    source = SOURCES["bytez"]
    register_credential("BYTEZ_API_KEY", "bytez-secret")
    seen: list[str] = []

    def urlopen(request, timeout=None, **_kwargs):
        seen.append(request.full_url)
        if "task=" in request.full_url:
            raise _http_500(request.full_url)
        return _Response(
            {
                "error": None,
                "output": [
                    {"modelId": "Qwen/Qwen3-4B", "task": "text-generation", "meterPrice": "0 / sec"},
                    {"modelId": "openai/whisper-large-v3", "task": "automatic-speech-recognition"},
                    {"modelId": "no-task/model"},
                ],
            }
        )

    with (
        patch("contextual_orchestrator.model_discovery._open_trusted_discovery_request", side_effect=urlopen),
        patch("contextual_orchestrator.model_discovery.time.sleep"),
    ):
        discovered = discover_provider_models(source)

    assert [model.model_id for model in discovered] == ["Qwen/Qwen3-4B"]
    assert seen[-1] == "https://api.bytez.com/models/v2/list/models"
    assert any(url.endswith("task=chat") for url in seen)
    assert any(url.endswith("task=text-generation") for url in seen)


def test_bytez_unfiltered_fallback_without_chat_rows_is_empty_catalog() -> None:
    source = SOURCES["bytez"]
    register_credential("BYTEZ_API_KEY", "bytez-secret")

    def urlopen(request, timeout=None, **_kwargs):
        if "task=" in request.full_url:
            return _Response({"error": None, "output": []})
        return _Response({"error": None, "output": [{"modelId": "a/asr", "task": "automatic-speech-recognition"}]})

    with (
        patch("contextual_orchestrator.model_discovery._open_trusted_discovery_request", side_effect=urlopen),
        pytest.raises(ProviderDiscoveryError) as excinfo,
    ):
        discover_provider_models(source)
    assert excinfo.value.error_code == "empty_provider_catalog"


def test_bytez_all_three_failures_report_the_last_http_status() -> None:
    source = SOURCES["bytez"]
    register_credential("BYTEZ_API_KEY", "bytez-secret")
    seen: list[str] = []

    def urlopen(request, timeout=None, **_kwargs):
        seen.append(request.full_url)
        raise _http_500(request.full_url)

    with (
        patch("contextual_orchestrator.model_discovery._open_trusted_discovery_request", side_effect=urlopen),
        patch("contextual_orchestrator.model_discovery.time.sleep"),
        pytest.raises(ProviderDiscoveryError) as excinfo,
    ):
        discover_provider_models(source)
    assert excinfo.value.error_code == "http_status_500"
    assert "https://api.bytez.com/models/v2/list/models" in seen


# --- Experiential Labs key spellings ------------------------------------


def test_explabs_env_names_prefer_correct_spelling() -> None:
    assert credential_env_names(EXPLABS_KV) == (
        "EXPERIENTIAL_LABS_API_KEY",
        "EXPERIENTAL_LABS_API_KEY",
        "EXPLABS_API_KEY",
    )
    assert credential_env_names("BYTEZ_API_KEY") == ("BYTEZ_API_KEY",)
    assert SOURCES["experiential_labs"].credential_name == EXPLABS_KV


@pytest.mark.parametrize(
    ("environ", "expected"),
    [
        ({"EXPERIENTIAL_LABS_API_KEY": "right", "EXPERIENTAL_LABS_API_KEY": "typo", "EXPLABS_API_KEY": "doc"}, "right"),
        ({"EXPERIENTIAL_LABS_API_KEY": "  ", "EXPERIENTAL_LABS_API_KEY": "typo\r\n", "EXPLABS_API_KEY": "doc"}, "typo"),
        ({"EXPLABS_API_KEY": "doc"}, "doc"),
        ({}, ""),
    ],
)
def test_explabs_bootstrap_value_order(environ, expected) -> None:
    assert bootstrap_credential_value(environ, EXPLABS_KV) == expected


def test_provider_bootstrap_registers_explabs_from_documented_name() -> None:
    values = collect_provider_credentials({"EXPLABS_API_KEY": "doc-key"}, require_all=False)
    assert values == {EXPLABS_KV: "doc-key"}


def test_review_gateway_registers_explabs_from_correct_spelling() -> None:
    registered = register_review_credentials(
        {"EXPERIENTIAL_LABS_API_KEY": "right-key", "EXPERIENTAL_LABS_API_KEY": "typo-key"},
        credential_names=(EXPLABS_KV,),
    )
    assert registered == (EXPLABS_KV,)
    from contextual_orchestrator.credentials import get_credential

    assert get_credential(EXPLABS_KV) == "right-key"


def test_seeded_gateway_pops_every_explabs_spelling(monkeypatch) -> None:
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "scripts" / "ci" / "serve_seeded_gateway.py"
    spec = importlib.util.spec_from_file_location("serve_seeded_gateway_under_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    for name in ("EXPERIENTIAL_LABS_API_KEY", "EXPERIENTAL_LABS_API_KEY", "EXPLABS_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("EXPERIENTAL_LABS_API_KEY", "typo-key")
    monkeypatch.setenv("EXPLABS_API_KEY", "doc-key")

    seeded = module.seed_credentials_from_bootstrap_env()

    from contextual_orchestrator.credentials import get_credential

    assert EXPLABS_KV in seeded
    assert get_credential(EXPLABS_KV) == "typo-key"
    assert "EXPLABS_API_KEY" not in os.environ
    assert "EXPERIENTAL_LABS_API_KEY" not in os.environ


# --- OpenCode Go protocol table and session header ----------------------


def test_go_table_matches_documented_protocols() -> None:
    assert opencode_go_model_endpoint("glm-5.3") == "chat/completions"
    assert opencode_go_model_endpoint("deepseek-v4.1-flash") == "chat/completions"
    assert opencode_go_model_endpoint("mimo-v2.6-pro") == "chat/completions"
    assert opencode_go_model_endpoint("grok-4.7") == "responses"
    assert opencode_go_model_endpoint("gpt-6-luna") == "responses"
    assert opencode_go_model_endpoint("minimax-m3") == "messages"
    assert opencode_go_model_endpoint("qwen3.8-max") == "messages"
    assert opencode_go_model_endpoint("unlisted-model") is None
    assert set(OPENCODE_GO_MODEL_ENDPOINTS.values()) == {"chat/completions", "responses", "messages"}


def test_go_serves_only_chat_completions_rows() -> None:
    rows = _parse_openai_compatible(
        {"data": [{"id": "deepseek-v4.1-flash"}, {"id": "grok-4.7"}, {"id": "qwen3.8-max"}, {"id": "glm-5"}]},
        SOURCES["opencode_go"],
    )
    assert {row.model_id: row.evidence_only for row in rows} == {
        "deepseek-v4.1-flash": False,
        "grok-4.7": True,
        "qwen3.8-max": True,
        "glm-5": True,
    }


def _agent(provider_name: str, base_url: str = "https://example.invalid/v1"):
    return SimpleNamespace(provider_name=provider_name, base_url=base_url)


def test_opencode_headers_only_for_opencode() -> None:
    payload = {"messages": [{"role": "user", "content": "hi"}]}
    assert opencode_request_headers(_agent("openrouter"), payload) == {}
    for agent in (_agent("opencode_go"), _agent("opencode_zen"), _agent("custom", "https://opencode.ai/zen/go/v1")):
        headers = opencode_request_headers(agent, payload)
        assert headers["user-agent"].startswith("contextual-orchestrator/")
        assert headers[OPENCODE_SESSION_HEADER].startswith("co-")
    assert opencode_request_headers(_agent("custom", "https://notopencode.ai/v1"), payload) == {}


def test_session_id_is_stable_across_turns_and_distinct_across_conversations() -> None:
    first_turn = {"messages": [{"role": "system", "content": "s"}, {"role": "user", "content": "task A"}]}
    later_turn = {
        "messages": [
            {"role": "system", "content": "s"},
            {"role": "user", "content": "task A"},
            {"role": "assistant", "content": "ok"},
            {"role": "user", "content": "more"},
        ]
    }
    other = {"messages": [{"role": "system", "content": "s"}, {"role": "user", "content": "task B"}]}
    assert opencode_session_id(first_turn) == opencode_session_id(later_turn)
    assert opencode_session_id(first_turn) != opencode_session_id(other)
    assert "task A" not in opencode_session_id(first_turn)


def test_session_id_prefers_caller_key() -> None:
    assert opencode_session_id({"prompt_cache_key": "conv-1", "messages": []}) == "conv-1"
    assert opencode_session_id({"metadata": {"session_id": "conv-2"}}) == "conv-2"
    assert opencode_session_id({"prompt_cache_key": "x" * 500}) == "x" * 128
