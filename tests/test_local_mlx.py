"""Explicit loopback mlx-lm transport without weakening remote egress rules."""

from __future__ import annotations

from pathlib import Path
import sys
import urllib.request
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent  # noqa: E402
from contextual_orchestrator.orchestrator import ModelClient  # noqa: E402


class _Response:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        import json

        return json.dumps(self.payload).encode("utf-8")


def test_mlx_loopback_uses_http_without_a_credential() -> None:
    agent = ModelAgent("local_agent", "local-model", base_url="mlx://127.0.0.1:8080/v1")
    client = ModelClient(max_retries=0, temperature=0.0, chat_template_args={"enable_thinking": False})
    seen = []

    def open_provider(request, _destination=None):
        seen.append(request)
        return _Response({
            "choices": [{"message": {"content": "local-ok"}}],
            "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
        })

    with patch.object(client, "_open_provider", side_effect=open_provider):
        assert client.chat(agent, [{"role": "user", "content": "ping"}]) == "local-ok"
    assert seen[0].full_url == "http://127.0.0.1:8080/v1/chat/completions"
    assert "Authorization" not in seen[0].headers
    import json

    assert json.loads(seen[0].data)["chat_template_kwargs"] == {"enable_thinking": False}
    assert client.take_usage()["total_tokens"] == 3


def test_reasoning_only_response_explains_local_template_fix() -> None:
    agent = ModelAgent("local_agent", "local-model", base_url="mlx://127.0.0.1:8080/v1")
    client = ModelClient(max_retries=0)
    with patch.object(
        client,
        "_open_provider",
        return_value=_Response({"choices": [{"message": {"reasoning": "still thinking"}}]}),
    ):
        try:
            client.chat(agent, [{"role": "user", "content": "ping"}])
        except RuntimeError as exc:
            assert "enable_thinking" in str(exc)
        else:  # pragma: no cover
            raise AssertionError("reasoning-only provider response must fail clearly")


def test_local_responses_passthrough_adapts_to_chat_transport() -> None:
    agent = ModelAgent("local_agent", "local-model", base_url="mlx://127.0.0.1:8080/v1")
    client = ModelClient(max_retries=0, chat_template_args={"enable_thinking": False})
    with patch.object(client, "_validate_provider", return_value=None), patch.object(
        client,
        "_send_raw_with_retry",
        return_value={
            "id": "chatcmpl-local",
            "model": "local-model",
            "created": 123,
            "choices": [{
                "message": {"role": "assistant", "content": "OK"},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
        },
    ) as send:
        response = client.proxy_send(
            agent,
            "responses",
            {
                "model": "local-model",
                "instructions": "Be concise.",
                "input": [{
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "ping"}],
                }],
                "stream": True,
                "tools": [{
                    "type": "function",
                    "name": "lookup",
                    "parameters": {"type": "object"},
                }],
            },
        )
    assert response["object"] == "response"
    assert response["output_text"] == "OK"
    forwarded = send.call_args.args[2]
    assert forwarded["messages"] == [
        {"role": "system", "content": "Be concise."},
        {"role": "user", "content": "ping"},
    ]
    assert forwarded["tools"] == [{
        "type": "function",
        "function": {"name": "lookup", "parameters": {"type": "object"}},
    }]
    assert forwarded["chat_template_kwargs"] == {"enable_thinking": False}


def test_remote_http_is_still_rejected() -> None:
    agent = ModelAgent("remote_agent", "remote-model", base_url="http://127.0.0.1:8080/v1")
    try:
        with patch("contextual_orchestrator.orchestrator.get_credential", return_value="local"):
            ModelClient(max_retries=0).chat(agent, [{"role": "user", "content": "ping"}])
    except RuntimeError as exc:
        assert "https" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("plain http provider must remain rejected")


def test_provider_transport_rejects_non_http_url_before_io() -> None:
    client = ModelClient(max_retries=0)
    request = urllib.request.Request("file:///tmp/not-a-provider", method="GET")
    try:
        client._open_provider(request)
    except RuntimeError as exc:
        assert "HTTP(S) URL" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("non-HTTP provider URL must be rejected")


def test_local_batch_preserves_ids_and_usage() -> None:
    agent = ModelAgent("local_agent", "local-model", base_url="mlx://127.0.0.1:8080/v1")
    client = ModelClient(max_retries=0, local_concurrency=2)
    calls = []

    def fake_chat(_agent, messages, temperature=None):
        calls.append((messages[0]["content"], temperature))
        client._local.usage = {"completion_tokens": 1}
        return messages[0]["content"]

    with patch.object(client, "chat", side_effect=fake_chat):
        result = client.batch_chat(
            agent,
            {"one": [{"role": "user", "content": "1"}], "two": [{"role": "user", "content": "2"}]},
            temperature=0.0,
        )
    assert {key: value["content"] for key, value in result.items()} == {"one": "1", "two": "2"}
    assert all(value["usage"] == {"completion_tokens": 1} for value in result.values())
    assert sorted(calls) == [("1", 0.0), ("2", 0.0)]


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
    print("ok")
