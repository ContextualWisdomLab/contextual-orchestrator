"""Concurrent virtual-route callers each keep their own tool_calls.

``ThreadingHTTPServer`` serves every request on its own thread while a single
``TaskOrchestrator`` is shared across all of them, so the pending assistant
extras (``tool_calls``/``finish_reason``) carried from ``_invoke`` to
``route_once`` must be per-thread. Held as plain instance state, a sibling
request's ``_invoke`` resets it between this thread's write and its read and
the tool call is silently dropped -- the caller receives an empty assistant
message instead of its function call, with no error.
"""

from __future__ import annotations

import threading
import types
from contextlib import contextmanager
from typing import Any

from contextual_orchestrator import ModelAgent, TaskOrchestrator

_PAIRS = 24


def _agents() -> list[ModelAgent]:
    return [
        ModelAgent(
            "primary_free_agent",
            "primary-free-model",
            priority=10,
            provider_name="primary",
            tags=("cost:free", "reasoning", "coding"),
        )
    ]


class _PerThreadToolCallClient:
    """Return tool_calls tagged with the calling thread's own request id."""

    def __init__(self) -> None:
        self._local = threading.local()

    def request_settings_snapshot(self) -> dict[str, Any]:
        """Report neutral sampling settings."""
        return {
            "temperature": None,
            "top_p": None,
            "presence_penalty": None,
            "frequency_penalty": None,
            "max_output_tokens": 64,
        }

    @contextmanager
    def request_settings(self, **overrides: Any):
        """Accept and ignore request-scoped overrides."""
        del overrides
        yield

    @contextmanager
    def suppress_request_tools(self):
        """Accept the non-worker tool suppression hop."""
        yield

    def chat(self, agent: ModelAgent, messages: list, **kwargs: Any) -> str:
        """Record this thread's tool call and return empty assistant text."""
        del agent, kwargs
        tag = messages[-1]["content"]
        self._local.extras = {
            "tool_calls": [
                {
                    "id": f"call_{tag}",
                    "type": "function",
                    "function": {"name": "inspect", "arguments": f'{{"who":"{tag}"}}'},
                }
            ],
            "finish_reason": "tool_calls",
        }
        return ""

    def take_usage(self) -> dict[str, Any] | None:
        """Report no usage."""
        return None

    def take_assistant_message(self) -> dict[str, Any] | None:
        """Hand back and clear this thread's pending extras."""
        extras = getattr(self._local, "extras", None)
        self._local.extras = None
        return extras


def test_concurrent_route_once_keeps_each_caller_tool_calls() -> None:
    """Two in-flight virtual-route callers must not lose or swap tool_calls."""
    orchestrator = TaskOrchestrator(_agents(), client=_PerThreadToolCallClient())
    barrier = threading.Barrier(2, timeout=15)
    unpatched = orchestrator._invoke

    def invoke_then_hold(self: Any, *args: Any, **kwargs: Any) -> Any:
        """Hold each thread between the extras write and route_once's read."""
        del self
        outcome = unpatched(*args, **kwargs)
        try:
            barrier.wait()
        except threading.BrokenBarrierError:  # pragma: no cover - timing guard
            pass
        return outcome

    # Timing only: no routing, selection, or response logic is changed.
    orchestrator._invoke = types.MethodType(invoke_then_hold, orchestrator)

    dropped: list[str] = []
    swapped: list[str] = []
    guard = threading.Lock()

    def call(tag: str) -> None:
        """Run one virtual-route request and check the tool_calls it got back."""
        result = orchestrator.route_once(
            [{"role": "user", "content": tag}], model_name=TaskOrchestrator.FREE_MODEL
        )
        calls = result.get("tool_calls")
        with guard:
            if not calls:
                dropped.append(tag)
            elif calls[0]["id"] != f"call_{tag}":
                swapped.append(f"{tag} got {calls[0]['id']}")

    try:
        for index in range(_PAIRS):
            barrier.reset()
            threads = [
                threading.Thread(target=call, args=(f"{side}{index}",))
                for side in ("first", "second")
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=20)
    finally:
        del orchestrator._invoke

    assert not swapped, f"tool_calls crossed between concurrent callers: {swapped[:3]}"
    assert not dropped, (
        f"tool_calls silently dropped for {len(dropped)} of {_PAIRS * 2} concurrent callers"
    )
