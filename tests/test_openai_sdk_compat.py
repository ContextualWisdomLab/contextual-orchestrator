"""Genuine OpenAI SDK compatibility for the org gap-review backlog (item 33).

Every test here instantiates the real ``openai`` package's client
(``openai.OpenAI(api_key=..., base_url=...)``) against a live gateway HTTP
server and drives it through the stock SDK's own methods -- never hand-rolled
JSON -- proving the fixed operations are actually reachable with an
unmodified SDK:

* ``client.batches.create/retrieve/list/cancel()`` (POST/GET ``/v1/batches``)
* ``client.audio.transcriptions.create(file=..., model=...)`` (always
  multipart/form-data -- there is no JSON-body form of this SDK call)
* ``client.chat.completions.create(modalities=["text","audio"], audio=...)``
  (the only SDK-native way to request spoken-audio chat output)

PR #1012 (chat<->responses shape translation) is a separate, unrelated gap
and is not touched here.
"""

from __future__ import annotations

import base64
import io
import json
import threading

import openai
import pytest

from contextual_orchestrator import ModelAgent, TaskOrchestrator
from contextual_orchestrator.server import SecurityConfig, _read_multipart_form, build_server

_TOKEN = "openai_sdk_compat_token"  # noqa: S105


class _FakeFileTransport:
    """Minimal in-memory file provider double -- upload really persists bytes.

    The gateway's own mock transport (``ModelClient._mock_raw``/``proxy_upload``)
    intentionally returns canned content on download regardless of what was
    uploaded (see test_files_api.py), which is fine for shape tests but makes
    a batch input file's real JSONL unrecoverable. This test double closes
    that loop: upload really stores what was sent, download really returns
    it -- exercising the real request/response shapes end to end, per this
    task's own "real or a test double at the transport layer" allowance.
    """

    def __init__(self) -> None:
        self._store: dict[str, bytes] = {}

    def proxy_upload(self, agent, endpoint, body, *, content_type, content_length, max_response_bytes):
        raw = body.read()
        fields = _read_multipart_form(raw, content_type)
        filename, content = fields["file"]
        provider_id = f"provider_file_{len(self._store)}"
        self._store[provider_id] = content
        return {
            "id": provider_id,
            "object": "file",
            "bytes": len(content),
            "created_at": 0,
            "purpose": fields.get("purpose", "batch"),
            "filename": filename,
            "status": "processed",
        }

    def proxy_get_bytes(self, agent, endpoint, *, max_response_bytes):
        provider_id = endpoint.split("/")[1]
        return self._store[provider_id], "application/jsonl"


def _start(orchestrator: TaskOrchestrator):
    server = build_server(orchestrator, port=0, security=SecurityConfig(auth_token=_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _client(port: int) -> openai.OpenAI:
    return openai.OpenAI(
        api_key=_TOKEN, base_url=f"http://127.0.0.1:{port}/v1", max_retries=0
    )


def _batch_input_jsonl(custom_ids: tuple[str, ...], *, model: str) -> bytes:
    lines = [
        json.dumps(
            {
                "custom_id": custom_id,
                "method": "POST",
                "url": "/v1/chat/completions",
                "body": {
                    "model": model,
                    "messages": [{"role": "user", "content": f"question for {custom_id}"}],
                },
            }
        )
        for custom_id in custom_ids
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


def test_sdk_batches_create_retrieve_list_cancel_round_trip() -> None:
    """client.batches.create/retrieve/list/cancel() against a real HTTP gateway.

    The default coordinator backs chat batches with LocalBatchBackend, which
    runs eagerly, so this batch is already "completed" -- with a real,
    downloadable output file -- by the time create() returns.
    """
    agent = ModelAgent("batch_worker", "mock-batch-model", tags=("reasoning", "files"))
    orchestrator = TaskOrchestrator([agent])
    transport = _FakeFileTransport()
    orchestrator.client.proxy_upload = transport.proxy_upload  # type: ignore[method-assign]
    orchestrator.client.proxy_get_bytes = transport.proxy_get_bytes  # type: ignore[method-assign]
    server, thread = _start(orchestrator)
    try:
        client = _client(server.server_address[1])
        uploaded = client.files.create(
            file=(
                "batch_input.jsonl",
                io.BytesIO(_batch_input_jsonl(("task_a", "task_b"), model="mock-batch-model")),
                "application/jsonl",
            ),
            purpose="batch",
        )
        assert uploaded.id.startswith("file_")
        assert uploaded.purpose is not None

        batch = client.batches.create(
            input_file_id=uploaded.id,
            endpoint="/v1/chat/completions",
            completion_window="24h",
        )
        assert batch.object == "batch"
        assert batch.input_file_id == uploaded.id
        assert batch.endpoint == "/v1/chat/completions"
        assert batch.status == "completed"
        assert batch.request_counts is not None
        assert batch.request_counts.total == 2
        assert batch.request_counts.completed == 2
        assert batch.output_file_id is not None

        retrieved = client.batches.retrieve(batch.id)
        assert retrieved.id == batch.id
        assert retrieved.status == "completed"
        assert retrieved.output_file_id == batch.output_file_id

        output_bytes = client.files.content(retrieved.output_file_id).read()
        output_lines = [
            json.loads(line)
            for line in output_bytes.decode("utf-8").splitlines()
            if line.strip()
        ]
        assert {line["custom_id"] for line in output_lines} == {"task_a", "task_b"}
        for line in output_lines:
            assert line["response"]["status_code"] == 200
            assert line["response"]["body"]["object"] == "chat.completion"
            assert line["response"]["body"]["choices"][0]["message"]["content"]

        listed = client.batches.list(limit=10)
        assert batch.id in [item.id for item in listed.data]

        # Cancelling an already-terminal batch is an idempotent no-op, same
        # as the real API -- it must not error or fabricate a status change.
        cancelled = client.batches.cancel(batch.id)
        assert cancelled.id == batch.id
        assert cancelled.status == "completed"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_sdk_batches_create_rejects_unsupported_endpoint() -> None:
    """A non-chat batch endpoint fails closed rather than being mishandled."""
    server, thread = _start(TaskOrchestrator([ModelAgent("worker_agent", "mock-model", tags=("files",))]))
    try:
        client = _client(server.server_address[1])
        uploaded = client.files.create(
            file=(
                "in.jsonl",
                io.BytesIO(
                    b'{"custom_id":"a","method":"POST","url":"/v1/embeddings","body":{}}\n'
                ),
                "application/jsonl",
            ),
            purpose="batch",
        )
        with pytest.raises(openai.BadRequestError) as excinfo:
            client.batches.create(
                input_file_id=uploaded.id,
                endpoint="/v1/embeddings",
                completion_window="24h",
            )
        assert excinfo.value.response.status_code == 400
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_sdk_batches_retrieve_unknown_id_is_a_real_404() -> None:
    server, thread = _start(TaskOrchestrator([ModelAgent("worker_agent", "mock-model", tags=("files",))]))
    try:
        client = _client(server.server_address[1])
        with pytest.raises(openai.NotFoundError):
            client.batches.retrieve("batch_does_not_exist")
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_sdk_audio_transcriptions_create_multipart_upload() -> None:
    """client.audio.transcriptions.create() always sends multipart/form-data.

    A test-double transport (matching this repo's own convention for
    exercising capability passthrough, see test_multimodal_model_group_http.py)
    returns a real Transcription shape and captures the routed payload, so
    this proves both genuine SDK parsing and that the multipart upload was
    translated into the internal input_audio shape faithfully.
    """
    agent = ModelAgent("transcribe_worker", "mock-transcribe", tags=("transcription",))
    orchestrator = TaskOrchestrator([agent])
    captured: dict = {}

    def fake_proxy_send(agent: ModelAgent, endpoint: str, payload: dict) -> dict:
        captured["endpoint"] = endpoint
        captured["payload"] = payload
        return {"text": "mock transcript text"}

    orchestrator.client.proxy_send = fake_proxy_send  # type: ignore[method-assign]
    server, thread = _start(orchestrator)
    try:
        client = _client(server.server_address[1])
        audio_bytes = b"RIFF....WAVEfmt fake-but-nonempty audio payload"
        transcript = client.audio.transcriptions.create(
            file=("clip.wav", io.BytesIO(audio_bytes), "audio/wav"),
            model="mock-transcribe",
            language="en",
            temperature=0.2,
        )
        assert transcript.text == "mock transcript text"
        assert captured["endpoint"] == "audio/transcriptions"
        payload = captured["payload"]
        assert payload["model"] == "mock-transcribe"
        assert payload["input_audio"]["format"] == "wav"
        assert base64.b64decode(payload["input_audio"]["data"]) == audio_bytes
        assert payload["language"] == "en"
        assert payload["temperature"] == pytest.approx(0.2)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_sdk_chat_completions_with_audio_output_modalities() -> None:
    """chat.completions.create(modalities=["text","audio"], audio={...}).

    The only SDK-native way to request spoken-audio chat output -- there is
    no separate client.audio.generations method. Routes to the same
    capability="audio" passthrough /v1/audio/generations already uses.
    """
    agent = ModelAgent("audio_worker", "mock-audio-preview", tags=("audio",))
    server, thread = _start(TaskOrchestrator([agent]))
    try:
        client = _client(server.server_address[1])
        completion = client.chat.completions.create(
            model="mock-audio-preview",
            messages=[{"role": "user", "content": "say hello out loud"}],
            modalities=["text", "audio"],
            audio={"voice": "alloy", "format": "wav"},
        )
        assert completion.object == "chat.completion"
        assert completion.model == "mock-audio-preview"
        assert completion.choices[0].message.content
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_sdk_chat_completions_audio_output_requires_no_audio_capable_agent_fails_closed() -> None:
    """Without an audio-capable agent, the SDK sees a real 503 -- not silence."""
    server, thread = _start(
        TaskOrchestrator([ModelAgent("text_only", "mock-planner", tags=("reasoning",))])
    )
    try:
        client = _client(server.server_address[1])
        with pytest.raises(openai.APIStatusError) as excinfo:
            client.chat.completions.create(
                model="mock-planner",
                messages=[{"role": "user", "content": "speak"}],
                modalities=["text", "audio"],
                audio={"voice": "alloy", "format": "wav"},
            )
        assert excinfo.value.response.status_code == 503
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
    print("ok")
