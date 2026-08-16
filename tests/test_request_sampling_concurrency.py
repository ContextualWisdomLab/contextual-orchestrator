"""Request-scoped generation options remain isolated across concurrent HTTP calls."""

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
from contextual_orchestrator.server import SecurityConfig, build_server  # noqa: E402

_TEST_AUTH_TOKEN = "request_sampling_concurrency_token"  # noqa: S105


class PausingClient(ModelClient):
    """Pause one overridden request while a default request enters the client."""

    def __init__(self) -> None:
        super().__init__()
        self.override_entered = threading.Event()
        self.release_override = threading.Event()
        self.observed: dict[str, tuple[object, ...]] = {}

    def chat(self, agent, messages, temperature=None, top_p=None):  # type: ignore[no-untyped-def]
        prompt = messages[-1]["content"]
        if prompt == "override request":
            self.override_entered.set()
            assert self.release_override.wait(timeout=5)
        answer = super().chat(agent, messages, temperature=temperature, top_p=top_p)
        self.observed[prompt] = (
            self._local.last_temperature,
            self._local.last_top_p,
            self._local.last_presence_penalty,
            self._local.last_frequency_penalty,
            self._local.last_max_output_tokens,
        )
        return answer


class FailingClient(ModelClient):
    """Fail once, then expose the next request's effective defaults."""

    def __init__(self) -> None:
        super().__init__()
        self.fail_next = True
        self.observed: list[tuple[object, ...]] = []

    def chat(self, agent, messages, temperature=None, top_p=None):  # type: ignore[no-untyped-def]
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("controlled provider failure")
        answer = super().chat(agent, messages, temperature=temperature, top_p=top_p)
        self.observed.append(
            (
                self._local.last_temperature,
                self._local.last_top_p,
                self._local.last_presence_penalty,
                self._local.last_frequency_penalty,
                self._local.last_max_output_tokens,
            )
        )
        return answer


def _post(port: int, payload: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "authorization": f"Bearer {_TEST_AUTH_TOKEN}",
            "connection": "close",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _server(client: ModelClient):
    orchestrator = TaskOrchestrator(
        [ModelAgent("general_agent", "mock-planner", tags=("reasoning", "writing"))],
        client=client,
    )
    server = build_server(
        orchestrator,
        port=0,
        security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def test_http_sampling_options_are_isolated_between_overlapping_requests() -> None:
    """A request without overrides must not inherit an overlapping request's knobs."""
    client = PausingClient()
    server, thread, port = _server(client)
    override_request = {
        "model": "mock-planner",
        "prompt": "override request",
        "temperature": 0.8,
        "top_p": 0.9,
        "presence_penalty": -0.4,
        "frequency_penalty": 0.5,
        "max_tokens": 222,
    }
    default_request = {"model": "mock-planner", "prompt": "default request"}
    responses: dict[str, tuple[int, dict]] = {}

    def call(label: str, payload: dict) -> None:
        responses[label] = _post(port, payload)

    try:
        override_thread = threading.Thread(target=call, args=("override", override_request))
        override_thread.start()
        assert client.override_entered.wait(timeout=5)

        default_thread = threading.Thread(target=call, args=("default", default_request))
        default_thread.start()
        default_thread.join(timeout=10)
        assert not default_thread.is_alive()
        assert responses["default"][0] == 200, responses["default"][1]
        assert client.observed["default request"] == (0.2, None, None, None, 2048)

        client.release_override.set()
        override_thread.join(timeout=10)
        assert not override_thread.is_alive()
        assert responses["override"][0] == 200, responses["override"][1]
        assert client.observed["override request"] == (0.8, 0.9, -0.4, 0.5, 222)
    finally:
        client.release_override.set()
        server.shutdown()
        thread.join(timeout=5)


def test_http_sampling_context_is_cleared_after_provider_failure() -> None:
    """A failed overridden request cannot poison the following default request."""
    client = FailingClient()
    server, thread, port = _server(client)
    try:
        status, _ = _post(
            port,
            {
                "model": "mock-planner",
                "prompt": "controlled failure",
                "temperature": 0.9,
                "top_p": 0.8,
                "presence_penalty": 0.7,
                "frequency_penalty": 0.6,
                "max_tokens": 333,
            },
        )
        assert status == 500

        status, body = _post(port, {"model": "mock-planner", "prompt": "default request"})
        assert status == 200, body
        assert client.observed == [(0.2, None, None, None, 2048)]
    finally:
        server.shutdown()
        thread.join(timeout=5)
