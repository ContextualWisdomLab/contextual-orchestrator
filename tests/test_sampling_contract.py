"""Tests for provider-neutral optional sampling request fields."""

from __future__ import annotations

import json

from contextual_orchestrator.orchestrator import ModelAgent, ModelClient


def _agent() -> ModelAgent:
    return ModelAgent(
        id="sampling_worker",
        model="provider/model",
        base_url="https://gateway.example.com",
        credential_key="",
    )


def test_model_client_owns_default_sampling_without_import_side_effects() -> None:
    client = ModelClient()

    assert client.default_temperature is None
    assert client.temperature is None


def test_stream_omits_unrequested_temperature_and_preserves_explicit_value(monkeypatch) -> None:
    client = ModelClient()
    captured: list[dict[str, object]] = []
    monkeypatch.setattr(client, "_validate_provider", lambda _agent: object())

    def stream_send(_agent, payload, _destination=None):
        captured.append(payload)
        return iter(["OK"])

    monkeypatch.setattr(client, "_stream_send", stream_send)

    assert list(client.stream_chat(_agent(), [{"role": "user", "content": "Sample."}])) == ["OK"]
    assert "temperature" not in captured[0]
    assert list(client.stream_chat(_agent(), [{"role": "user", "content": "Sample."}], temperature=0.2)) == ["OK"]
    assert captured[1]["temperature"] == 0.2


def test_batch_omits_unrequested_temperature_and_preserves_explicit_value(monkeypatch) -> None:
    client = ModelClient()
    uploaded: list[list[dict[str, object]]] = []

    def batch_upload(_agent, payload, _destination=None):
        uploaded.append([json.loads(line) for line in payload.decode("utf-8").splitlines()])
        return "file_001"

    monkeypatch.setattr(client, "_batch_upload", batch_upload)

    def batch_json(_agent, method, path, body=None, destination=None):
        del path, body, destination
        if method == "POST":
            return {"id": "batch_001"}
        return {"status": "completed", "output_file_id": "file_002"}

    monkeypatch.setattr(client, "_batch_json", batch_json)
    monkeypatch.setattr(
        client,
        "_batch_raw",
        lambda *_args, **_kwargs: (
            b'{"custom_id":"request_1","response":{"body":{"choices":[{"message":'
            b'{"content":"OK"}}]}}}'
        ),
    )

    client._batch_run(
        _agent(),
        {"request_1": [{"role": "user", "content": "Sample."}]},
        None,
        0.0,
        1.0,
    )
    assert "temperature" not in uploaded[0][0]["body"]

    client._batch_run(
        _agent(),
        {"request_2": [{"role": "user", "content": "Sample."}]},
        0.2,
        0.0,
        1.0,
    )
    assert uploaded[1][0]["body"]["temperature"] == 0.2
