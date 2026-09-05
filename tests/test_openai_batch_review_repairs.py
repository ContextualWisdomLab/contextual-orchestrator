"""Regression tests for the OpenAI Batch and transcription review repairs."""

from __future__ import annotations

import json
import math

import pytest

from contextual_orchestrator.batch_routing import BatchRequest, LocalBatchBackend
from contextual_orchestrator.server import RequestError, _batch_output_jsonl_line, _parse_batch_input_jsonl


def _line(body: dict, *, url: str = "/v1/chat/completions") -> bytes:
    return (json.dumps({"custom_id": "item", "method": "POST", "url": url, "body": body}) + "\n").encode()


def test_batch_parser_requires_matching_endpoint_and_preserves_options() -> None:
    body = {
        "model": "mock-model",
        "messages": [{"role": "user", "content": "hello"}],
        "temperature": 0.25,
        "max_completion_tokens": 32,
        "response_format": {"type": "json_object"},
    }
    request = _parse_batch_input_jsonl(
        _line(body), endpoint="/v1/chat/completions", zdr_only=False
    )[0]
    assert request.parameters == {
        "temperature": 0.25,
        "max_completion_tokens": 32,
        "response_format": {"type": "json_object"},
    }
    assert request.to_jsonl_line()["body"] == body

    with pytest.raises(RequestError, match="url must match"):
        _parse_batch_input_jsonl(
            _line(body, url="/v1/embeddings"),
            endpoint="/v1/chat/completions",
            zdr_only=False,
        )


def test_local_batch_applies_preserved_options() -> None:
    captured: dict = {}

    def runner(messages, mode, model, parameters):
        captured.update(parameters)
        return {"answer": "ok", "mode": mode}

    backend = LocalBatchBackend(runner)
    job = backend.submit([
        BatchRequest(
            messages=[{"role": "user", "content": "hello"}],
            parameters={"temperature": 0.2},
        )
    ])
    assert backend.retrieve(job)[0].answer == "ok"
    assert captured == {"temperature": 0.2}


def test_unknown_batch_usage_stays_unknown() -> None:
    line = json.loads(
        _batch_output_jsonl_line(
            {"custom_id": "item", "answer": "ok", "prompt_tokens": None, "completion_tokens": None},
            model="mock-model",
        )
    )
    assert line["response"]["body"]["usage"] is None


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_batch_request_rejects_non_finite_temperature(value: float) -> None:
    with pytest.raises(RequestError, match="finite"):
        _parse_batch_input_jsonl(
            _line({
                "model": "mock-model",
                "messages": [{"role": "user", "content": "hello"}],
                "temperature": value,
            }),
            endpoint="/v1/chat/completions",
            zdr_only=False,
        )
