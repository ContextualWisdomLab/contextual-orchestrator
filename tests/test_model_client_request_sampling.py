"""Request-scoped ModelClient sampling stays isolated across concurrent threads.

A commercial gateway serves Completions and chat on ThreadingHTTPServer with one
shared ModelClient. Buyers sending two in-flight requests with different
temperatures must not observe each other's knobs. This test uses true concurrent
threads and the mock worker so the isolation is measured, not assumed.
"""

from __future__ import annotations

import threading
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent  # noqa: E402
from contextual_orchestrator.orchestrator import ModelClient  # noqa: E402


def _mock_agent() -> ModelAgent:
    return ModelAgent("general_agent", "mock-planner", tags=("reasoning", "writing"))


def test_request_sampling_is_thread_local() -> None:
    """Two concurrent chats keep their own temperature; process default stays 0.2."""
    client = ModelClient()
    agent = _mock_agent()
    seen: dict[str, float] = {}
    errors: list[BaseException] = []
    barrier = threading.Barrier(2)

    def run(name: str, temperature: float) -> None:
        try:
            with client.apply_request_sampling(temperature=temperature):
                barrier.wait(timeout=5)
                client.chat(agent, [{"role": "user", "content": f"temp={temperature}"}])
                seen[name] = float(client._local.last_temperature)
        except BaseException as exc:  # noqa: BLE001 - collect for the joining thread
            errors.append(exc)

    cool = threading.Thread(target=run, args=("cool", 0.1))
    hot = threading.Thread(target=run, args=("hot", 1.9))
    cool.start()
    hot.start()
    cool.join(timeout=10)
    hot.join(timeout=10)
    assert not errors, errors
    assert seen == {"cool": 0.1, "hot": 1.9}
    assert client.default_temperature == 0.2


def test_request_sampling_does_not_leak_after_exit() -> None:
    """After the context exits, the next chat on this thread uses process defaults."""
    client = ModelClient()
    agent = _mock_agent()
    with client.apply_request_sampling(temperature=0.9, max_output_tokens=128):
        client.chat(agent, [{"role": "user", "content": "inside"}])
        assert client._local.last_temperature == 0.9
        assert client._local.last_max_output_tokens == 128
    client.chat(agent, [{"role": "user", "content": "after"}])
    assert client._local.last_temperature == 0.2
    assert client._local.last_max_output_tokens == client.max_output_tokens
    assert client.default_temperature == 0.2


def test_request_sampling_call_kwargs_override_thread_knobs() -> None:
    """Explicit chat(temperature=...) still wins over apply_request_sampling."""
    client = ModelClient()
    agent = _mock_agent()
    with client.apply_request_sampling(temperature=0.1):
        client.chat(agent, [{"role": "user", "content": "override"}], temperature=0.8)
        assert client._local.last_temperature == 0.8


if __name__ == "__main__":
    test_request_sampling_is_thread_local()
    test_request_sampling_does_not_leak_after_exit()
    test_request_sampling_call_kwargs_override_thread_knobs()
    print("ok")
