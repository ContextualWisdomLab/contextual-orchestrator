"""HTTP end-to-end contracts for the opt-in observed-health quarantine.

Each of the four served paths behind ``/v1/chat/completions`` -- route
(``route_once``), conduct, streaming (``stream_route``) and the structured
provider path (``proxy_completion``) -- must apply the same policy when
``observed_health_quarantine=True``: (a) one slow failure demotes the member
for the next request, (b) after the cooldown the half-open probe recovers on
success or doubles the cooldown on failure, and (c) an all-quarantined pool
still serves, least-recently-failed first. Providers are a controllable
in-process client over ``mock://`` agents; time is the breaker's injected
monotonic clock, so nothing sleeps.
"""

from __future__ import annotations

import io
import json
import logging
import sys
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.orchestrator import ModelClient  # noqa: E402
from contextual_orchestrator.provider_errors import ProviderUpstreamError  # noqa: E402
from contextual_orchestrator.server import SecurityConfig, build_server  # noqa: E402

_TOKEN = "observed_health_quarantine_http_token"
_TAGS = ("reasoning", "writing", "planning", "coding", "implementation", "verification", "review")
_PATHS = ("route", "conduct", "stream", "proxy")


def _timeout(agent: ModelAgent, transport: str) -> ProviderUpstreamError:
    return ProviderUpstreamError(
        agent_id=agent.id,
        model=agent.model,
        error_code="provider_timeout",
        message="provider timed out",
        client_status=504,
        provider_status=504,
        retryable=True,
        transport=transport,
    )


class _ControlledProvider(ModelClient):
    """Every served transport fails with a slow-class 504 for agents in ``down``."""

    def __init__(self) -> None:
        super().__init__()
        self.down: set[str] = set()
        self.calls: list[str] = []
        self._lock = threading.Lock()

    def _attempt(self, agent: ModelAgent, transport: str) -> None:
        with self._lock:
            self.calls.append(agent.id)
        if agent.id in self.down:
            raise _timeout(agent, transport)

    def chat(self, agent: ModelAgent, messages: list, *args: Any, **kwargs: Any) -> str:  # type: ignore[override]
        self._attempt(agent, "chat")
        return f"answer from {agent.id}"

    def stream_chat(self, agent: ModelAgent, messages: list, *args: Any, **kwargs: Any):  # type: ignore[override]
        self._attempt(agent, "stream")
        yield f"answer from {agent.id}"

    def proxy_send_once(self, agent: ModelAgent, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:  # type: ignore[override]
        self._attempt(agent, "passthrough")
        return {
            "id": "chatcmpl_test",
            "object": "chat.completion",
            "model": agent.model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": json.dumps({"answer": agent.id})},
                    "finish_reason": "stop",
                }
            ],
        }

    proxy_send = proxy_send_once

    def take_usage(self) -> None:
        return None


class _Clock:
    def __init__(self) -> None:
        self.now = 10_000.0

    def __call__(self) -> float:
        return self.now


@contextmanager
def _gateway(enabled: bool = True) -> Iterator[tuple[TaskOrchestrator, _ControlledProvider, _Clock, int]]:
    agents = [
        ModelAgent("slow_worker", "slow-model", base_url="mock://slow.example", tags=_TAGS, priority=10),
        ModelAgent("steady_worker", "steady-model", base_url="mock://steady.example", tags=_TAGS, priority=1),
    ]
    provider = _ControlledProvider()
    orchestrator = TaskOrchestrator(
        agents,
        client=provider,
        tool_retry_backoff_seconds=0.0,
        observed_health_quarantine=enabled,
    )
    orchestrator.policy = replace(orchestrator.policy, realtime_judge=False)
    orchestrator.tool_retry_attempts = 0
    clock = _Clock()
    orchestrator._circuit_clock = clock
    server = build_server(orchestrator, port=0, security=SecurityConfig(auth_token=_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield orchestrator, provider, clock, server.server_address[1]
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def _body(path: str) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": TaskOrchestrator.AUTO_MODEL,
        "messages": [{"role": "user", "content": "summarize the incident"}],
    }
    if path == "proxy":
        # Virtual selector + response_format: the structured provider path
        # (proxy_completion(single_agent=False) -> conduct stages + structured
        # synthesis failover), the HTTP route that reaches proxy_completion.
        body["response_format"] = {"type": "json_object"}
    else:
        body["mode"] = "conduct" if path == "conduct" else "route"
    if path == "stream":
        body["stream"] = True
    return body


def _send(port: int, path: str) -> int:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/chat/completions",
        data=json.dumps(_body(path)).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "authorization": f"Bearer {_TOKEN}",
            "connection": "close",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = response.read().decode("utf-8")
            status = response.status
    except urllib.error.HTTPError as exc:
        with exc:
            exc.read()
            return exc.code
    if path == "stream" and '"error"' in payload:
        return 502  # a terminal SSE error frame after the 200 header
    return status


def _request(orchestrator: TaskOrchestrator, provider: _ControlledProvider, port: int, path: str) -> tuple[int, list[str]]:
    provider.calls.clear()
    status = _send(port, path)
    return status, list(provider.calls)


def _state(orchestrator: TaskOrchestrator, agent_id: str) -> dict[str, Any]:
    return orchestrator.circuit_health_snapshot()[agent_id]


@contextmanager
def _captured(level: int) -> Iterator[io.StringIO]:
    logger = logging.getLogger("contextual_orchestrator.orchestrator")
    previous_level, previous_propagate = logger.level, logger.propagate
    buffer = io.StringIO()
    handler = logging.StreamHandler(buffer)
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
    try:
        yield buffer
    finally:
        logger.removeHandler(handler)
        handler.close()
        logger.setLevel(previous_level)
        logger.propagate = previous_propagate


def _quarantine_slow_worker(orchestrator, provider, port, path) -> None:
    """Drive both members down so ``slow_worker`` reaches two slow strikes."""
    provider.down = {"slow_worker"}
    status, calls = _request(orchestrator, provider, port, path)
    assert status == 200 and calls[:2] == ["slow_worker", "steady_worker"], (status, calls)
    provider.down = {"slow_worker", "steady_worker"}
    _request(orchestrator, provider, port, path)
    assert _state(orchestrator, "slow_worker")["state"] == "open"


@pytest.mark.parametrize("path", _PATHS)
def test_one_slow_failure_demotes_member_for_next_http_request(path: str) -> None:
    with _gateway() as (orchestrator, provider, _clock, port):
        provider.down = {"slow_worker"}
        status, calls = _request(orchestrator, provider, port, path)
        assert status == 200, (path, status, calls)
        assert calls[:2] == ["slow_worker", "steady_worker"], (path, calls)
        assert _state(orchestrator, "slow_worker")["state"] == "closed"  # demoted, not quarantined

        status, calls = _request(orchestrator, provider, port, path)
        assert status == 200, (path, status, calls)
        assert "slow_worker" not in calls, (path, calls)
        assert calls[0] == "steady_worker", (path, calls)


@pytest.mark.parametrize("path", _PATHS)
def test_half_open_probe_recovers_on_success_over_http(path: str) -> None:
    with _gateway() as (orchestrator, provider, clock, port):
        _quarantine_slow_worker(orchestrator, provider, port, path)
        provider.down = set()
        status, calls = _request(orchestrator, provider, port, path)
        assert status == 200 and "slow_worker" not in calls, (path, status, calls)

        clock.now += _state(orchestrator, "slow_worker")["cooldown_seconds"]
        provider.down = {"steady_worker"}  # the demoted half-open member is reached
        with _captured(logging.INFO) as buffer:
            status, calls = _request(orchestrator, provider, port, path)
        assert status == 200 and "slow_worker" in calls, (path, status, calls)
        assert "circuit_half_open agent_id=slow_worker" in buffer.getvalue()
        assert "circuit_recovered agent_id=slow_worker" in buffer.getvalue()
        assert _state(orchestrator, "slow_worker")["state"] == "closed"


@pytest.mark.parametrize("path", _PATHS)
def test_half_open_probe_failure_doubles_cooldown_over_http(path: str) -> None:
    with _gateway() as (orchestrator, provider, clock, port):
        _quarantine_slow_worker(orchestrator, provider, port, path)
        first = _state(orchestrator, "slow_worker")["cooldown_seconds"]
        clock.now += first
        provider.down = {"slow_worker", "steady_worker"}
        with _captured(logging.WARNING) as buffer:
            _request(orchestrator, provider, port, path)
        assert "trigger=half_open_failure" in buffer.getvalue(), (path, buffer.getvalue())
        assert _state(orchestrator, "slow_worker")["state"] == "open"
        assert _state(orchestrator, "slow_worker")["cooldown_seconds"] == 2 * first


@pytest.mark.parametrize("path", _PATHS)
def test_all_quarantined_pool_still_serves_least_recently_failed_first(path: str) -> None:
    with _gateway() as (orchestrator, provider, clock, port):
        _quarantine_slow_worker(orchestrator, provider, port, path)
        clock.now += 5.0
        provider.down = {"steady_worker"}
        _request(orchestrator, provider, port, path)  # steady's second slow strike
        assert _state(orchestrator, "steady_worker")["state"] == "open"

        provider.down = set()
        with _captured(logging.WARNING) as buffer:
            status, calls = _request(orchestrator, provider, port, path)
        assert status == 200, (path, status, calls)
        assert calls[0] == "slow_worker", (path, calls)  # failed longest ago
        assert "circuit_all_open_fallback" in buffer.getvalue()


def test_auto_mode_triage_pick_follows_observed_health() -> None:
    """The uncached triage call is one direct pick; it must not re-hit a demoted member."""
    with _gateway() as (orchestrator, provider, _clock, port):
        provider.down = {"slow_worker"}
        _request(orchestrator, provider, port, "route")  # slow strike: demoted
        provider.calls.clear()
        body = {
            "model": TaskOrchestrator.AUTO_MODEL,
            "messages": [{"role": "user", "content": "triage this distinct prompt"}],
        }
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={"content-type": "application/json", "authorization": f"Bearer {_TOKEN}"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            assert response.status == 200
            response.read()
        assert "slow_worker" not in provider.calls, provider.calls


def test_flag_off_http_route_keeps_legacy_order() -> None:
    with _gateway(enabled=False) as (orchestrator, provider, _clock, port):
        provider.down = {"slow_worker"}
        _request(orchestrator, provider, port, "route")
        status, calls = _request(orchestrator, provider, port, "route")
        assert status == 200 and calls == ["slow_worker", "steady_worker"]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
