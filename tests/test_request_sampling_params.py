"""OpenAI temperature / max_tokens sampling on the orchestrated route path."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.orchestrator import ModelClient  # noqa: E402
from contextual_orchestrator.server import SecurityConfig, _validate_sampling, build_server  # noqa: E402

_TEST_AUTH_TOKEN = "sampling_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_validate_sampling_accepts_temperature_and_max_tokens() -> None:
    assert _validate_sampling({"temperature": 0.7, "max_tokens": 32}) == {
        "temperature": 0.7,
        "max_tokens": 32,
    }
    assert _validate_sampling({"max_completion_tokens": 16}) == {"max_tokens": 16}
    assert _validate_sampling({"n": 1}) is None
    assert _validate_sampling({"top_p": 0.9, "seed": 42}) == {"top_p": 0.9, "seed": 42}
    assert _validate_sampling({"presence_penalty": 0.5, "frequency_penalty": -0.5}) == {
        "presence_penalty": 0.5,
        "frequency_penalty": -0.5,
    }


def test_validate_sampling_rejects_bad_n_and_temperature() -> None:
    from contextual_orchestrator.server import RequestError

    try:
        _validate_sampling({"n": 2})
        raise AssertionError("expected invalid_n")
    except RequestError as exc:
        assert exc.code == "invalid_n"
    try:
        _validate_sampling({"temperature": 3.5})
        raise AssertionError("expected invalid_temperature")
    except RequestError as exc:
        assert exc.code == "invalid_temperature"
    try:
        _validate_sampling({"max_tokens": 0})
        raise AssertionError("expected invalid_max_tokens")
    except RequestError as exc:
        assert exc.code == "invalid_max_tokens"
    try:
        _validate_sampling({"top_p": 1.5})
        raise AssertionError("expected invalid_top_p")
    except RequestError as exc:
        assert exc.code == "invalid_top_p"
    try:
        _validate_sampling({"seed": 1.2})
        raise AssertionError("expected invalid_seed")
    except RequestError as exc:
        assert exc.code == "invalid_seed"
    try:
        _validate_sampling({"presence_penalty": 3})
        raise AssertionError("expected invalid_presence_penalty")
    except RequestError as exc:
        assert exc.code == "invalid_presence_penalty"


def test_mock_client_truncates_to_max_tokens() -> None:
    """Buyer path: max_tokens caps output length (offline mock ~4 chars/token)."""
    client = ModelClient()
    agent = ModelAgent("general_agent", "mock-generalist")
    messages = [{"role": "user", "content": "please write a long detailed answer about systems"}]
    full = client.chat(agent, messages)
    capped = client.chat(agent, messages, max_tokens=5)
    assert len(full) > len(capped)
    assert len(capped) <= 5 * 4
    assert full.startswith(capped)


def test_route_once_honors_max_tokens() -> None:
    orchestrator = build()
    messages = [{"role": "user", "content": "please write a long detailed answer about systems"}]
    full = orchestrator.route_once(messages)
    capped = orchestrator.route_once(messages, sampling={"max_tokens": 8})
    assert len(full["answer"]) > len(capped["answer"])
    assert len(capped["answer"]) <= 8 * 4


def test_http_rejects_n_greater_than_one() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            data=json.dumps(
                {
                    "messages": [{"role": "user", "content": "hi"}],
                    "n": 3,
                }
            ).encode("utf-8"),
            headers={
                "content-type": "application/json",
                "authorization": f"Bearer {_TEST_AUTH_TOKEN}",
                "connection": "close",
            },
            method="POST",
        )
        try:
            urllib.request.urlopen(request, timeout=5)
            raise AssertionError("expected HTTPError")
        except urllib.error.HTTPError as exc:
            body = json.loads(exc.read().decode("utf-8"))
            assert exc.code == 400
            assert body["error"]["code"] == "invalid_n"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_stop_sequence_truncates_mock_output() -> None:
    client = ModelClient()
    agent = ModelAgent("general_agent", "mock-generalist")
    messages = [{"role": "user", "content": "please write a long detailed answer about systems"}]
    full = client.chat(agent, messages)
    # Use a substring that appears mid-answer so stop is exercised for real.
    mid = full[len(full) // 3 : len(full) // 3 + 8]
    assert mid, full
    stopped = client.chat(agent, messages, stop=[mid])
    assert mid not in stopped
    assert full.startswith(stopped)
    assert len(stopped) < len(full)


def test_http_stop_string_shortens_answer() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    url = f"http://127.0.0.1:{port}/v1/chat/completions"

    def post(payload: dict) -> str:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "content-type": "application/json",
                "authorization": f"Bearer {_TEST_AUTH_TOKEN}",
                "connection": "close",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            body = json.loads(response.read().decode("utf-8"))
            return body["choices"][0]["message"]["content"]

    try:
        base = {
            "messages": [{"role": "user", "content": "please write a long detailed answer about systems"}],
            "orchestration": "route",
        }
        full = post(base)
        marker = full[len(full) // 4 : len(full) // 4 + 6]
        stopped = post({**base, "stop": marker})
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert marker not in stopped
    assert full.startswith(stopped)


def test_http_max_tokens_shortens_route_answer() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    url = f"http://127.0.0.1:{port}/v1/chat/completions"

    def post(payload: dict) -> dict:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "content-type": "application/json",
                "authorization": f"Bearer {_TEST_AUTH_TOKEN}",
                "connection": "close",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))

    try:
        base_payload = {
            "messages": [{"role": "user", "content": "please write a long detailed answer about systems"}],
            "orchestration": "route",
        }
        full = post(base_payload)
        capped = post({**base_payload, "max_tokens": 6, "temperature": 0.0})
    finally:
        server.shutdown()
        thread.join(timeout=5)

    full_text = full["choices"][0]["message"]["content"]
    capped_text = capped["choices"][0]["message"]["content"]
    assert len(full_text) > len(capped_text)
    assert len(capped_text) <= 6 * 4


if __name__ == "__main__":
    test_validate_sampling_accepts_temperature_and_max_tokens()
    test_validate_sampling_rejects_bad_n_and_temperature()
    test_mock_client_truncates_to_max_tokens()
    test_route_once_honors_max_tokens()
    test_stop_sequence_truncates_mock_output()
    test_http_stop_string_shortens_answer()
    test_http_rejects_n_greater_than_one()
    test_http_max_tokens_shortens_route_answer()
    print("ok")
