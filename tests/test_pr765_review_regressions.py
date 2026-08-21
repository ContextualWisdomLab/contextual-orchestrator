"""Regression contracts for the PR 765 review findings."""

from __future__ import annotations

import json
import urllib.error
from unittest.mock import patch

import pytest

from contextual_orchestrator import orchestrator as orchestration
from contextual_orchestrator import server
from contextual_orchestrator.orchestrator import ModelAgent, ModelClient, TaskOrchestrator


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "object", "properties": []},
        {"type": "object", "required": ["answer", 7]},
        {"type": "array", "items": []},
    ],
)
def test_malformed_json_schema_is_rejected_before_response_validation(schema) -> None:
    with pytest.raises(server.RequestError) as captured:
        server._validate_chat_response_format(
            {
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {"name": "answer", "schema": schema},
                }
            }
        )
    assert captured.value.status == 400
    assert captured.value.code == "invalid_response_format"


@pytest.mark.parametrize(
    "field",
    [
        "temperature",
        "top_p",
        "presence_penalty",
        "frequency_penalty",
        "seed",
        "stop",
        "logit_bias",
        "logprobs",
        "top_logprobs",
    ],
)
def test_unapplied_responses_controls_fail_closed(field) -> None:
    values = {
        "temperature": 0.2,
        "top_p": 0.9,
        "presence_penalty": 0.1,
        "frequency_penalty": -0.1,
        "seed": 42,
        "stop": ["END"],
        "logit_bias": {"1": 1},
        "logprobs": True,
        "top_logprobs": 3,
    }
    with pytest.raises(server.RequestError) as captured:
        server._reject_responses_orchestration_controls({field: values[field]})
    assert captured.value.status == 422
    assert captured.value.code == "unsupported_responses_orchestration_controls"
    assert captured.value.detail == {"fields": [field]}


def test_empty_responses_controls_remain_omit_equivalent() -> None:
    server._reject_responses_orchestration_controls(
        {
            "temperature": None,
            "stop": "",
            "logit_bias": {},
            "logprobs": False,
            "top_logprobs": 0,
        }
    )


def test_internal_chat_preserves_explicit_temperature(monkeypatch) -> None:
    """An explicit caller sampling control remains an honest provider passthrough."""
    client = ModelClient()
    agent = ModelAgent(
        id="chat_worker",
        model="provider/model",
        base_url="https://gateway.example.com",
        credential_key="",
    )
    captured: dict[str, object] = {}

    monkeypatch.setattr(client, "_validate_provider", lambda _agent: None)

    def capture_payload(_agent, payload, _destination=None, *, timeout=None):
        del timeout
        captured.update(payload)
        return "OK"

    monkeypatch.setattr(client, "_send", capture_payload)

    assert client.chat(
        agent,
        [{"role": "user", "content": "Sample."}],
        temperature=0.2,
    ) == "OK"
    assert captured["temperature"] == 0.2


@pytest.mark.parametrize(
    "userinfo_url",
    [
        "https://@gateway.example.com/v1/models",
        "https://:secret@gateway.example.com/v1/models",
    ],
)
def test_provider_json_rejects_empty_userinfo_before_provider_transport(userinfo_url: str) -> None:
    """An empty username or password is still userinfo and cannot bypass origin checks."""
    agent = ModelAgent(
        id="model_discovery_agent",
        model="model_catalog",
        base_url="https://gateway.example.com/v1",
        credential_key="",
    )
    client = ModelClient()
    with (
        patch.object(client, "_validate_provider") as validate_provider,
        patch.object(client, "_open_provider") as open_provider,
        pytest.raises(RuntimeError, match="validated agent origin"),
    ):
        client.fetch_json(agent, userinfo_url)
    validate_provider.assert_not_called()
    open_provider.assert_not_called()


@pytest.mark.parametrize(
    "schema",
    [
        [],
        {"properties": {"answer": []}},
        {"anyOf": {}},
    ],
)
def test_json_schema_definition_rejects_invalid_nested_containers(schema) -> None:
    with pytest.raises(server.RequestError, match="must") as captured:
        server._validate_json_schema_definition(schema)
    assert captured.value.status == 400


def test_json_schema_definition_accepts_recursive_items_and_any_of() -> None:
    server._validate_json_schema_definition(
        {
            "type": "array",
            "items": {"anyOf": [{"type": "string"}, {"type": "integer"}]},
        }
    )


@pytest.mark.parametrize(
    ("value", "schema"),
    [
        ("answer", []),
        ("answer", {"enum": ["other"]}),
        ("answer", {"const": "other"}),
        ("answer", {"anyOf": [{"type": "integer"}]}),
        ("answer", {"type": "object"}),
        ({}, {"type": "object", "required": ["answer"]}),
        ({"other": 1}, {"type": "object", "properties": {}, "additionalProperties": False}),
        ("answer", {"type": "array"}),
        (1, {"type": "string"}),
        ("true", {"type": "boolean"}),
        (True, {"type": "integer"}),
        (True, {"type": "number"}),
    ],
)
def test_structured_value_validation_rejects_every_supported_mismatch(value, schema) -> None:
    with pytest.raises(server.RequestError) as captured:
        server._validate_json_schema_value(value, schema)
    assert captured.value.status == 502


def test_structured_value_validation_recurses_through_objects_and_arrays() -> None:
    schema = {
        "type": "object",
        "required": ["answers"],
        "properties": {"answers": {"type": "array", "items": {"type": "string"}}},
        "additionalProperties": False,
    }
    server._validate_json_schema_value({"answers": ["yes"]}, schema)
    assert server._json_schema_matches("yes", {"type": "string"}) is True


@pytest.mark.parametrize(
    ("answer", "response_format"),
    [
        (None, {"type": "json_object"}),
        ("not-json", {"type": "json_object"}),
        ("[]", {"type": "json_object"}),
    ],
)
def test_structured_completion_rejects_non_contract_answers(answer, response_format) -> None:
    with pytest.raises(server.RequestError) as captured:
        server._validate_structured_completion_answer(answer, response_format)
    assert captured.value.status == 502


def test_structured_completion_applies_json_schema() -> None:
    server._validate_structured_completion_answer(
        json.dumps({"answer": "yes"}),
        {
            "type": "json_schema",
            "json_schema": {
                "schema": {
                    "type": "object",
                    "properties": {"answer": {"type": "string"}},
                    "required": ["answer"],
                }
            },
        },
    )


def test_responses_chat_content_ignores_non_content_items() -> None:
    assert orchestration._responses_chat_content(None) == ""
    assert orchestration._responses_chat_content(["one", 2, {"text": "two"}]) == "onetwo"


def test_temperature_capability_rejection_preserves_http_error_body() -> None:
    class _UnreadableBody:
        def read(self) -> bytes:
            raise OSError("closed")

        def close(self) -> None:
            return None

    assert orchestration._temperature_capability_rejection(ValueError("temperature")) is False
    error = urllib.error.HTTPError(
        "https://gateway.example/v1/chat/completions",
        400,
        "temperature is unsupported; only the default value is accepted",
        {},
        _UnreadableBody(),
    )
    assert orchestration._temperature_capability_rejection(error) is True
    assert error.read() == b""


def test_embedding_model_requires_an_orchestrator_when_omitted() -> None:
    with pytest.raises(server.RequestError) as captured:
        server._validate_embeddings_model({})
    assert captured.value.code == "invalid_model"


def test_response_content_and_capability_selection_fail_closed() -> None:
    agent = ModelAgent("general_agent", "mock-model")
    with pytest.raises(RuntimeError, match="assistant content"):
        ModelClient._response_content(agent, {"choices": [{"message": {}}]})

    orchestrator = TaskOrchestrator([agent])
    with pytest.raises(ValueError, match="non-empty"):
        orchestrator.select_capability_agent(" ")
    with pytest.raises(RuntimeError, match="capability=embedding"):
        orchestrator.select_capability_agent("embedding")
