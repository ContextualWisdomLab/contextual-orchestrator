"""Bytez unfiltered fallback, Experiential registered key name, and OpenCode Go protocol/session contracts.

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
    MAX_DISCOVERY_RESPONSE_BYTES,
    OPENCODE_GO_MODEL_ENDPOINTS,
    PROVIDER_MODEL_SOURCES,
    ProviderDiscoveryError,
    _parse_openai_compatible,
    bootstrap_credential_value,
    discover_all_models,
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
    def __init__(self, payload=None, *, raw: bytes | None = None):
        import json

        self._body = raw if raw is not None else json.dumps(payload).encode("utf-8")

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
                    {
                        "modelId": "Qwen/Qwen3-4B",
                        "task": "text-generation",
                        "meterPrice": "0 / sec",
                    },
                    {
                        "modelId": "openai/whisper-large-v3",
                        "task": "automatic-speech-recognition",
                    },
                    {"modelId": "no-task/model"},
                ],
            }
        )

    with (
        patch(
            "contextual_orchestrator.model_discovery._open_trusted_discovery_request",
            side_effect=urlopen,
        ),
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
        return _Response(
            {
                "error": None,
                "output": [
                    {"modelId": "a/asr", "task": "automatic-speech-recognition"}
                ],
            }
        )

    with (
        patch(
            "contextual_orchestrator.model_discovery._open_trusted_discovery_request",
            side_effect=urlopen,
        ),
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
        patch(
            "contextual_orchestrator.model_discovery._open_trusted_discovery_request",
            side_effect=urlopen,
        ),
        patch("contextual_orchestrator.model_discovery.time.sleep"),
        pytest.raises(ProviderDiscoveryError) as excinfo,
    ):
        discover_provider_models(source)
    assert excinfo.value.error_code == "http_status_500"
    assert "https://api.bytez.com/models/v2/list/models" in seen


_BYTEZ_UNFILTERED_URL = "https://api.bytez.com/models/v2/list/models"
_OPEN = "contextual_orchestrator.model_discovery._open_trusted_discovery_request"
_SLEEP = "contextual_orchestrator.model_discovery.time.sleep"


def _http_error(url: str, code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(url, code, "error", hdrs=None, fp=None)


@pytest.mark.parametrize(
    "bad_task",
    [["chat"], {"name": "text-generation"}],
    ids=["list-task", "dict-task"],
)
def test_bytez_unfiltered_fallback_skips_unhashable_task_rows(bad_task) -> None:
    """A list/dict ``task`` must be skipped, not raise ``TypeError: unhashable``."""
    source = SOURCES["bytez"]
    register_credential("BYTEZ_API_KEY", "bytez-secret")

    def urlopen(request, timeout=None, **_kwargs):
        if "task=" in request.full_url:
            raise _http_500(request.full_url)
        return _Response(
            {
                "error": None,
                "output": [
                    {"modelId": "bad/unhashable-task", "task": bad_task},
                    {"modelId": "Qwen/Qwen3-4B", "task": "chat"},
                ],
            }
        )

    with patch(_OPEN, side_effect=urlopen), patch(_SLEEP):
        discovered = discover_provider_models(source)

    assert [model.model_id for model in discovered] == ["Qwen/Qwen3-4B"]


@pytest.mark.parametrize(
    "bad_task",
    [["chat"], {"name": "chat"}],
    ids=["list-task", "dict-task"],
)
def test_bytez_unhashable_task_rows_do_not_abort_other_providers(bad_task) -> None:
    """Malformed Bytez rows must not escape discover_all_models and drop every provider."""
    register_credential("BYTEZ_API_KEY", "bytez-secret")
    register_credential(EXPLABS_KV, "experiential-secret")

    def urlopen(request, timeout=None, **_kwargs):
        url = request.full_url
        if url.startswith("https://api.experientiallabs.ai/"):
            return _Response(
                {
                    "object": "list",
                    "data": [{"id": "explabs-chat-1", "object": "model"}],
                }
            )
        if "task=" in url:
            raise _http_500(url)
        # Only unhashable-task rows: Bytez ends up with no chat models.
        return _Response(
            {"error": None, "output": [{"modelId": "bad/row", "task": bad_task}]}
        )

    with patch(_OPEN, side_effect=urlopen), patch(_SLEEP):
        models, errors = discover_all_models(
            (SOURCES["bytez"], SOURCES["experiential_labs"]),
            discovery_deadline=None,
        )

    assert [(model.provider_name, model.model_id) for model in models] == [
        ("experiential_labs", "explabs-chat-1")
    ]
    assert [(error.provider_name, error.error_code) for error in errors] == [
        ("bytez", "http_status_500")
    ]


def _fallback_failure_timeout(url: str):
    raise TimeoutError("fixture timeout")


def _fallback_failure_503(url: str):
    raise _http_error(url, 503)


def _fallback_invalid_json(url: str):
    return _Response(raw=b"not json")


def _fallback_oversized(url: str):
    return _Response(raw=b" " * (MAX_DISCOVERY_RESPONSE_BYTES + 1))


def _fallback_no_chat_rows(url: str):
    return _Response(
        {
            "error": None,
            "output": [{"modelId": "a/asr", "task": "automatic-speech-recognition"}],
        }
    )


def _fallback_empty(url: str):
    return _Response({"error": None, "output": []})


@pytest.mark.parametrize(
    "fallback",
    [
        _fallback_failure_timeout,
        _fallback_failure_503,
        _fallback_invalid_json,
        _fallback_oversized,
        _fallback_no_chat_rows,
        _fallback_empty,
    ],
    ids=[
        "timeout",
        "http-503",
        "invalid-json",
        "oversized-body",
        "no-chat-rows",
        "empty",
    ],
)
def test_bytez_failed_fallback_keeps_original_http_status(fallback) -> None:
    """Filtered 500 + failing/empty unfiltered fallback must still report http_status_500."""
    source = SOURCES["bytez"]
    register_credential("BYTEZ_API_KEY", "bytez-secret")
    seen: list[str] = []

    def urlopen(request, timeout=None, **_kwargs):
        seen.append(request.full_url)
        if "task=" in request.full_url:
            raise _http_500(request.full_url)
        return fallback(request.full_url)

    with (
        patch(_OPEN, side_effect=urlopen),
        patch(_SLEEP),
        pytest.raises(ProviderDiscoveryError) as excinfo,
    ):
        discover_provider_models(source)

    assert excinfo.value.error_code == "http_status_500"
    assert _BYTEZ_UNFILTERED_URL in seen


def test_bytez_first_http_failure_wins_over_later_filtered_failure() -> None:
    source = SOURCES["bytez"]
    register_credential("BYTEZ_API_KEY", "bytez-secret")

    def urlopen(request, timeout=None, **_kwargs):
        url = request.full_url
        if url.endswith("task=chat"):
            raise _http_500(url)
        if "task=" in url:
            raise TimeoutError("fixture timeout")
        raise _http_error(url, 502)

    with (
        patch(_OPEN, side_effect=urlopen),
        patch(_SLEEP),
        pytest.raises(ProviderDiscoveryError) as excinfo,
    ):
        discover_provider_models(source)
    assert excinfo.value.error_code == "http_status_500"


@pytest.mark.parametrize("status", [401, 403])
def test_bytez_auth_failure_skips_unfiltered_fallback(status) -> None:
    """A refused key must not spend another call on the unfiltered catalog."""
    source = SOURCES["bytez"]
    register_credential("BYTEZ_API_KEY", "bytez-secret")
    seen: list[str] = []

    def urlopen(request, timeout=None, **_kwargs):
        seen.append(request.full_url)
        if "task=" in request.full_url:
            raise _http_error(request.full_url, status)
        return _Response(
            {"error": None, "output": [{"modelId": "Qwen/Qwen3-4B", "task": "chat"}]}
        )

    with (
        patch(_OPEN, side_effect=urlopen),
        patch(_SLEEP),
        pytest.raises(ProviderDiscoveryError) as excinfo,
    ):
        discover_provider_models(source)

    assert excinfo.value.error_code == f"http_status_{status}"
    assert _BYTEZ_UNFILTERED_URL not in seen
    assert all("task=" in url for url in seen)


def test_bytez_non_http_filtered_failure_is_kept_when_fallback_is_empty() -> None:
    source = SOURCES["bytez"]
    register_credential("BYTEZ_API_KEY", "bytez-secret")

    def urlopen(request, timeout=None, **_kwargs):
        if "task=" in request.full_url:
            raise TimeoutError("fixture timeout")
        return _Response({"error": None, "output": []})

    with (
        patch(_OPEN, side_effect=urlopen),
        patch(_SLEEP),
        pytest.raises(ProviderDiscoveryError) as excinfo,
    ):
        discover_provider_models(source)
    assert excinfo.value.error_code == "timeout"


# --- Experiential Labs registered key name ------------------------------

_UNREGISTERED_EXPLABS_SPELLINGS = ("EXPERIENTIAL_LABS_API_KEY", "EXPLABS_API_KEY")


def test_explabs_kv_name_is_the_registered_spelling() -> None:
    assert SOURCES["experiential_labs"].credential_name == EXPLABS_KV


@pytest.mark.parametrize(
    ("environ", "expected"),
    [
        ({"EXPERIENTAL_LABS_API_KEY": "registered"}, "registered"),
        ({"EXPERIENTAL_LABS_API_KEY": "registered\r\n"}, "registered"),
        (
            {
                "EXPERIENTAL_LABS_API_KEY": "registered",
                "EXPERIENTIAL_LABS_API_KEY": "other",
                "EXPLABS_API_KEY": "doc",
            },
            "registered",
        ),
        ({"EXPERIENTIAL_LABS_API_KEY": "other", "EXPLABS_API_KEY": "doc"}, ""),
        ({"EXPERIENTAL_LABS_API_KEY": "  ", "EXPLABS_API_KEY": "doc"}, ""),
        ({}, ""),
    ],
)
def test_explabs_bootstrap_reads_only_registered_name(environ, expected) -> None:
    assert bootstrap_credential_value(environ, EXPLABS_KV) == expected


def test_provider_bootstrap_ignores_unregistered_explabs_spellings() -> None:
    environ = {name: "shell-key" for name in _UNREGISTERED_EXPLABS_SPELLINGS}
    environ["BYTEZ_API_KEY"] = "bytez-key"
    assert collect_provider_credentials(environ, require_all=False) == {
        "BYTEZ_API_KEY": "bytez-key"
    }
    del environ["BYTEZ_API_KEY"]
    environ[EXPLABS_KV] = "registered-key"
    assert collect_provider_credentials(environ, require_all=False) == {
        EXPLABS_KV: "registered-key"
    }


def test_review_gateway_registers_only_registered_explabs_name() -> None:
    from contextual_orchestrator.credentials import get_credential

    registered = register_review_credentials(
        {name: "shell-key" for name in _UNREGISTERED_EXPLABS_SPELLINGS},
        credential_names=(EXPLABS_KV,),
    )
    assert registered == ()

    registered = register_review_credentials(
        {EXPLABS_KV: "registered-key", "EXPERIENTIAL_LABS_API_KEY": "shell-key"},
        credential_names=(EXPLABS_KV,),
    )
    assert registered == (EXPLABS_KV,)
    assert get_credential(EXPLABS_KV) == "registered-key"


def _load_seeded_gateway():
    import importlib.util
    from pathlib import Path

    path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "ci"
        / "serve_seeded_gateway.py"
    )
    spec = importlib.util.spec_from_file_location(
        "serve_seeded_gateway_under_test", path
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _clear_seeded_env(monkeypatch, module) -> None:
    for name in (
        *module.PROVIDER_KEY_ENV_NAMES,
        module.SERVER_AUTH_ENV_NAME,
        *_UNREGISTERED_EXPLABS_SPELLINGS,
    ):
        monkeypatch.delenv(name, raising=False)


def test_seeded_gateway_reads_only_registered_explabs_name(monkeypatch) -> None:
    from contextual_orchestrator.credentials import get_credential

    module = _load_seeded_gateway()
    _clear_seeded_env(monkeypatch, module)
    monkeypatch.setenv("EXPERIENTIAL_LABS_API_KEY", "shell-key")
    monkeypatch.setenv("EXPLABS_API_KEY", "doc-key")

    assert EXPLABS_KV not in module.seed_credentials_from_bootstrap_env()

    monkeypatch.setenv(EXPLABS_KV, "registered-key\r\n")
    seeded = module.seed_credentials_from_bootstrap_env()
    assert EXPLABS_KV in seeded
    assert get_credential(EXPLABS_KV) == "registered-key"
    assert EXPLABS_KV not in os.environ


@pytest.mark.parametrize("blank", ["", "   ", "\t", "\r\n", " \r\n"])
def test_seeded_gateway_skips_blank_values_and_pops_them(monkeypatch, blank) -> None:
    from contextual_orchestrator.credentials import get_credential

    module = _load_seeded_gateway()
    _clear_seeded_env(monkeypatch, module)
    monkeypatch.setenv("BYTEZ_API_KEY", blank)
    monkeypatch.setenv(EXPLABS_KV, "registered-key")

    seeded = module.seed_credentials_from_bootstrap_env()

    assert "BYTEZ_API_KEY" not in seeded
    assert get_credential("BYTEZ_API_KEY") is None
    assert seeded == [EXPLABS_KV]
    assert "BYTEZ_API_KEY" not in os.environ


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
    assert set(OPENCODE_GO_MODEL_ENDPOINTS.values()) == {
        "chat/completions",
        "responses",
        "messages",
    }


def test_go_serves_only_chat_completions_rows() -> None:
    rows = _parse_openai_compatible(
        {
            "data": [
                {"id": "deepseek-v4.1-flash"},
                {"id": "grok-4.7"},
                {"id": "qwen3.8-max"},
                {"id": "glm-5"},
            ]
        },
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
    for agent in (
        _agent("opencode_go"),
        _agent("opencode_zen"),
        _agent("custom", "https://opencode.ai/zen/go/v1"),
    ):
        headers = opencode_request_headers(agent, payload)
        assert headers["user-agent"].startswith("contextual-orchestrator/")
        assert headers[OPENCODE_SESSION_HEADER].startswith("co-")
    assert (
        opencode_request_headers(_agent("custom", "https://notopencode.ai/v1"), payload)
        == {}
    )


def test_session_id_is_stable_across_turns_and_distinct_across_conversations() -> None:
    first_turn = {
        "messages": [
            {"role": "system", "content": "s"},
            {"role": "user", "content": "task A"},
        ]
    }
    later_turn = {
        "messages": [
            {"role": "system", "content": "s"},
            {"role": "user", "content": "task A"},
            {"role": "assistant", "content": "ok"},
            {"role": "user", "content": "more"},
        ]
    }
    other = {
        "messages": [
            {"role": "system", "content": "s"},
            {"role": "user", "content": "task B"},
        ]
    }
    assert opencode_session_id(first_turn) == opencode_session_id(later_turn)
    assert opencode_session_id(first_turn) != opencode_session_id(other)
    assert "task A" not in opencode_session_id(first_turn)


def test_session_id_prefers_caller_key() -> None:
    assert (
        opencode_session_id({"prompt_cache_key": "conv-1", "messages": []}) == "conv-1"
    )
    assert opencode_session_id({"metadata": {"session_id": "conv-2"}}) == "conv-2"
    assert opencode_session_id({"prompt_cache_key": "x" * 500}) == "x" * 128
