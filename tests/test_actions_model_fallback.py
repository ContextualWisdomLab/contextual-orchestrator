"""Virtual selectors keep tools on Fugu route / TRINITY-Conductor conduct.

Incident: ContextualWisdomLab/.github run 34079284863, job 101622944649,
step 23. Strix called ``orchestrator/free`` with tools and streaming. The
gateway took single-agent passthrough and returned ``500 internal_error``
instead of re-selecting a worker on the control plane.

Callers use virtual models only. A tools array is a worker payload, not a
reason to leave route/conduct. Concrete model ids remain a debug pin.
"""

from __future__ import annotations

import json
import sys
import threading
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from contextual_orchestrator import ModelAgent, TaskOrchestrator
from contextual_orchestrator.provider_errors import ProviderUpstreamError
from contextual_orchestrator.server import SecurityConfig, build_server

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_TEST_AUTH_TOKEN = "virtual_tools_control_plane_token"  # noqa: S105
_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "inspect_repository",
            "description": "Inspect the trusted workspace",
            "parameters": {"type": "object", "properties": {}},
        },
    }
]


def _post(port: int, payload: dict[str, Any]) -> tuple[int, dict[str, Any] | str, str]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/chat/completions",
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
            content_type = response.headers.get("content-type", "")
            body = response.read().decode("utf-8")
            if content_type.startswith("text/event-stream"):
                return response.status, body, content_type
            return response.status, json.loads(body), content_type
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8")), "application/json"


def _free_agents() -> list[ModelAgent]:
    return [
        ModelAgent(
            "primary_free_agent",
            "primary-free-model",
            priority=10,
            provider_name="primary",
            tags=("cost:free", "reasoning", "coding"),
        ),
        ModelAgent(
            "fallback_free_agent",
            "fallback-free-model",
            priority=1,
            provider_name="fallback",
            tags=("cost:free", "reasoning", "coding"),
        ),
    ]


def test_http_virtual_free_tools_stay_on_route() -> None:
    """orchestrator/free + tools is Fugu route, not single-agent passthrough."""
    orchestrator = TaskOrchestrator(_free_agents())
    server = build_server(
        orchestrator, port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN)
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, body, content_type = _post(
            server.server_address[1],
            {
                "model": TaskOrchestrator.FREE_MODEL,
                "messages": [{"role": "user", "content": "scan the trusted workspace"}],
                "tools": _TOOLS,
            },
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert status == 200, body
    assert "json" in content_type
    assert isinstance(body, dict)
    assert body["object"] == "chat.completion"
    assert body["orchestration"]["mode"] == "route"
    assert "echo" not in body


def test_http_virtual_free_tools_stream_stays_on_control_plane() -> None:
    """stream=true does not eject virtual tool calls into passthrough."""
    orchestrator = TaskOrchestrator(_free_agents())
    server = build_server(
        orchestrator, port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN)
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, body, content_type = _post(
            server.server_address[1],
            {
                "model": TaskOrchestrator.FREE_MODEL,
                "messages": [{"role": "user", "content": "scan the trusted workspace"}],
                "tools": _TOOLS,
                "stream": True,
            },
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert status == 200, body
    assert content_type.startswith("text/event-stream")
    assert isinstance(body, str)
    assert "chat.completion.chunk" in body
    assert '"mode": "route"' in body or '"mode":"route"' in body


class _FailThenServeClient:
    """First free worker fails retryable; the next worker serves."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.tool_payloads: list[Any] = []
        self._settings: dict[str, Any] = {}

    def request_settings_snapshot(self) -> dict[str, Any]:
        return {
            "temperature": None,
            "top_p": None,
            "presence_penalty": None,
            "frequency_penalty": None,
            "max_output_tokens": 256,
            **self._settings,
        }

    @contextmanager
    def request_settings(self, **overrides: Any):
        previous = dict(self._settings)
        self._settings.update(
            {key: value for key, value in overrides.items() if value is not None}
        )
        try:
            yield
        finally:
            self._settings = previous

    @contextmanager
    def suppress_request_tools(self):
        previous = dict(self._settings)
        for key in ("tools", "tool_choice", "parallel_tool_calls"):
            self._settings.pop(key, None)
        try:
            yield
        finally:
            self._settings = previous

    def chat(self, agent: ModelAgent, messages: list, **kwargs: Any) -> str:
        del messages, kwargs
        self.calls.append(agent.id)
        self.tool_payloads.append(self.request_settings_snapshot().get("tools"))
        if agent.id == "primary_free_agent":
            raise ProviderUpstreamError(
                agent_id=agent.id,
                model=agent.model,
                error_code="server_error",
                message="provider rejected the request with HTTP 500",
                client_status=502,
                provider_status=500,
                retryable=True,
                transport="chat",
            )
        return f"served-by-{agent.id}"

    def take_usage(self) -> None:
        return None

    def stream_chat(self, agent: ModelAgent, messages: list, **kwargs: Any):
        content = self.chat(agent, messages, **kwargs)
        yield content


def test_http_virtual_free_tools_reselect_worker_on_retryable_failure() -> None:
    """A failed worker is replaced on route/_invoke, not by passthrough hopping."""
    client = _FailThenServeClient()
    orchestrator = TaskOrchestrator(_free_agents(), client=client)
    server = build_server(
        orchestrator, port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN)
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, body, _content_type = _post(
            server.server_address[1],
            {
                "model": TaskOrchestrator.FREE_MODEL,
                "messages": [{"role": "user", "content": "scan the trusted workspace"}],
                "tools": _TOOLS,
            },
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert status == 200, body
    assert isinstance(body, dict)
    assert body["orchestration"]["mode"] == "route"
    assert "served-by-fallback_free_agent" in body["choices"][0]["message"]["content"]
    assert client.calls[0] == "primary_free_agent"
    assert client.calls[-1] == "fallback_free_agent"
    assert "fallback_free_agent" in client.calls
    assert _TOOLS in client.tool_payloads


def test_http_virtual_chat_completions_stream_has_no_responses_reasoning_events() -> None:
    """Chat Completions cannot carry Responses think/reasoning events."""
    orchestrator = TaskOrchestrator(_free_agents())
    server = build_server(
        orchestrator, port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN)
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, body, content_type = _post(
            server.server_address[1],
            {
                "model": TaskOrchestrator.FREE_MODEL,
                "messages": [{"role": "user", "content": "scan the trusted workspace"}],
                "stream": True,
            },
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert status == 200, body
    assert content_type.startswith("text/event-stream")
    assert isinstance(body, str)
    assert "chat.completion.chunk" in body
    assert "response.reasoning_text" not in body
    assert "response.reasoning_summary" not in body
    assert "event: response." not in body


def test_http_virtual_chat_stream_reselects_worker_before_first_delta() -> None:
    """Fugu route on Chat Completions still changes worker before any SSE byte."""
    client = _FailThenServeClient()
    orchestrator = TaskOrchestrator(_free_agents(), client=client)
    server = build_server(
        orchestrator, port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN)
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, body, content_type = _post(
            server.server_address[1],
            {
                "model": TaskOrchestrator.FREE_MODEL,
                "messages": [{"role": "user", "content": "one short sentence"}],
                "stream": True,
            },
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert status == 200, body
    assert content_type.startswith("text/event-stream")
    assert isinstance(body, str)
    assert "served-by-fallback_free_agent" in body
    assert "response.reasoning_text" not in body
    assert client.calls[0] == "primary_free_agent"
    assert client.calls[-1] == "fallback_free_agent"


class _CapabilityFailThenServeClient:
    """First capability worker fails retryable; the next worker serves."""

    timeout = 30.0

    def __init__(self) -> None:
        self.calls: list[str] = []

    def proxy_send(self, agent: ModelAgent, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        del endpoint, payload
        self.calls.append(agent.id)
        if agent.id.startswith("primary_"):
            raise ProviderUpstreamError(
                agent_id=agent.id,
                model=agent.model,
                error_code="server_error",
                message="provider rejected the request with HTTP 500",
                client_status=502,
                provider_status=500,
                retryable=True,
                transport="capability",
            )
        return {"model": agent.model, "object": "image", "data": []}

    def proxy_send_bytes(
        self, agent: ModelAgent, endpoint: str, payload: dict[str, Any]
    ) -> tuple[bytes, str]:
        del endpoint, payload
        self.calls.append(agent.id)
        if agent.id.startswith("primary_"):
            raise ProviderUpstreamError(
                agent_id=agent.id,
                model=agent.model,
                error_code="server_error",
                message="provider rejected the request with HTTP 500",
                client_status=502,
                provider_status=500,
                retryable=True,
                transport="speech",
            )
        return b"fallback-audio", "audio/mpeg"


def _post_path(port: int, path: str, payload: dict[str, Any]) -> tuple[int, bytes, str]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "authorization": f"Bearer {_TEST_AUTH_TOKEN}",
            "connection": "close",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.status, response.read(), response.headers.get_content_type()


def test_http_virtual_free_image_reselects_worker() -> None:
    """orchestrator/free on /v1/images/generations re-selects after a 500."""
    client = _CapabilityFailThenServeClient()
    orchestrator = TaskOrchestrator(
        [
            ModelAgent(
                "primary_image",
                "primary-image",
                priority=10,
                tags=("image", "cost:free"),
            ),
            ModelAgent(
                "fallback_image",
                "fallback-image",
                priority=1,
                tags=("image", "cost:free"),
            ),
        ],
        client=client,
    )
    server = build_server(
        orchestrator, port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN)
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, raw, content_type = _post_path(
            server.server_address[1],
            "/v1/images/generations",
            {
                "model": TaskOrchestrator.FREE_MODEL,
                "prompt": "a schematic of the control plane",
            },
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    decoded = raw.decode("utf-8")
    body = json.loads(decoded)
    assert status == 200, body
    assert "json" in content_type
    assert body["model"] == "fallback-image"
    assert "response.reasoning_text" not in decoded
    assert client.calls == ["primary_image", "fallback_image"]


def test_http_virtual_free_speech_reselects_worker() -> None:
    """orchestrator/free on /v1/audio/speech re-selects after a 500."""
    client = _CapabilityFailThenServeClient()
    orchestrator = TaskOrchestrator(
        [
            ModelAgent(
                "primary_speech",
                "primary-speech",
                priority=10,
                tags=("speech", "cost:free"),
            ),
            ModelAgent(
                "fallback_speech",
                "fallback-speech",
                priority=1,
                tags=("speech", "cost:free"),
            ),
        ],
        client=client,
    )
    server = build_server(
        orchestrator, port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN)
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, raw, content_type = _post_path(
            server.server_address[1],
            "/v1/audio/speech",
            {
                "model": TaskOrchestrator.FREE_MODEL,
                "input": "hello from the control plane",
                "voice": "alloy",
            },
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert status == 200, raw
    assert content_type.startswith("audio/")
    assert raw == b"fallback-audio"
    assert client.calls == ["primary_speech", "fallback_speech"]


class _ToolCallClient:
    """Selected worker returns a Chat Completions tool call, not assistant text."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self._settings: dict[str, Any] = {}
        self._extras: dict[str, Any] | None = None

    def request_settings_snapshot(self) -> dict[str, Any]:
        return {
            "temperature": None,
            "top_p": None,
            "presence_penalty": None,
            "frequency_penalty": None,
            "max_output_tokens": 256,
            **self._settings,
        }

    @contextmanager
    def request_settings(self, **overrides: Any):
        previous = dict(self._settings)
        self._settings.update(
            {key: value for key, value in overrides.items() if value is not None}
        )
        try:
            yield
        finally:
            self._settings = previous

    def chat(self, agent: ModelAgent, messages: list, **kwargs: Any) -> str:
        del messages, kwargs
        self.calls.append(agent.id)
        self._extras = {
            "tool_calls": [
                {
                    "id": "call_inspect",
                    "type": "function",
                    "function": {
                        "name": "inspect_repository",
                        "arguments": "{}",
                    },
                }
            ],
            "finish_reason": "tool_calls",
        }
        return ""

    def take_usage(self) -> None:
        return None

    def take_assistant_message(self) -> dict[str, Any] | None:
        extras = self._extras
        self._extras = None
        return extras


def test_http_virtual_free_tools_preserve_provider_tool_calls() -> None:
    """Virtual + tools stays on route and returns the worker's tool_calls."""
    client = _ToolCallClient()
    orchestrator = TaskOrchestrator(_free_agents(), client=client)
    server = build_server(
        orchestrator, port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN)
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, body, _content_type = _post(
            server.server_address[1],
            {
                "model": TaskOrchestrator.FREE_MODEL,
                "messages": [{"role": "user", "content": "scan the trusted workspace"}],
                "tools": _TOOLS,
                "tool_choice": "required",
            },
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert status == 200, body
    assert isinstance(body, dict)
    message = body["choices"][0]["message"]
    assert message["content"] is None
    assert message["tool_calls"][0]["function"]["name"] == "inspect_repository"
    assert body["choices"][0]["finish_reason"] == "tool_calls"
    assert body["orchestration"]["mode"] == "route"


def test_conduct_does_not_forward_tools_to_non_worker_roles() -> None:
    """Caller tools stay on the worker hop, not thinker/verifier/synthesizer."""
    payloads: list[Any] = []

    class RecordingClient(_FailThenServeClient):
        def chat(self, agent: ModelAgent, messages: list, **kwargs: Any) -> str:
            del agent
            payloads.append(self.request_settings_snapshot().get("tools"))
            return "paper-role-output"

        def take_assistant_message(self) -> None:
            return None

    client = RecordingClient()
    orchestrator = TaskOrchestrator(_free_agents(), client=client)
    with client.request_settings(tools=_TOOLS, tool_choice="auto"):
        result = orchestrator.conduct(
            [{"role": "user", "content": "write one short sentence"}]
        )
    assert result["answer"]
    assert payloads
    assert payloads.count(_TOOLS) == 1
    assert payloads.count(None) == len(payloads) - 1


def test_conduct_two_argument_progress_callback_still_completes() -> None:
    """Existing two-argument conduct progress hooks keep working."""
    seen: list[tuple[str, str]] = []

    def progress(role: str, status: str) -> None:
        seen.append((role, status))

    orchestrator = TaskOrchestrator(_free_agents())
    result = orchestrator.conduct(
        [{"role": "user", "content": "write one short sentence"}],
        progress=progress,
    )
    assert result["answer"]
    assert seen
    assert all(len(item) == 2 for item in seen)
