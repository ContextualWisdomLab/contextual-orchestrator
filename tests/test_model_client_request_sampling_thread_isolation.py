"""Request-scoped sampling knobs must not leak across ThreadingHTTPServer workers.

The Completions and chat handlers used to write ``default_temperature`` (and
siblings) on the shared ``ModelClient``. Two overlapping requests could each
observe the other's knobs. Overrides live on the calling thread only.
"""

from __future__ import annotations

import threading
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator.orchestrator import ModelAgent, ModelClient  # noqa: E402


def test_model_client_request_sampling_stays_on_calling_thread() -> None:
    client = ModelClient()
    client.default_temperature = 0.2
    barrier = threading.Barrier(2)
    seen: dict[str, float] = {}
    errors: list[BaseException] = []

    def worker(label: str, temperature: float) -> None:
        try:
            with client.request_sampling(temperature=temperature):
                barrier.wait()
                agent = ModelAgent("probe_agent", "mock-planner", tags=("reasoning",))
                client.chat(agent, [{"role": "user", "content": label}])
                seen[label] = float(client._local.last_temperature)
        except BaseException as exc:  # noqa: BLE001 - collect for the parent thread
            errors.append(exc)

    threads = [
        threading.Thread(target=worker, args=("hot", 1.5)),
        threading.Thread(target=worker, args=("cold", 0.0)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
    assert not errors, errors
    assert seen == {"hot": 1.5, "cold": 0.0}
    assert client.default_temperature == 0.2


def test_model_client_request_sampling_restores_defaults_on_the_same_thread() -> None:
    client = ModelClient()
    client.default_temperature = 0.2
    agent = ModelAgent("probe_agent", "mock-planner", tags=("reasoning",))
    with client.request_sampling(temperature=1.1, top_p=0.4, max_output_tokens=32):
        client.chat(agent, [{"role": "user", "content": "inside"}])
        assert client._local.last_temperature == 1.1
        assert client._local.last_top_p == 0.4
    client.chat(agent, [{"role": "user", "content": "after"}])
    assert client._local.last_temperature == 0.2
    assert client._local.last_top_p is None
    assert client.max_output_tokens == 2048


if __name__ == "__main__":
    test_model_client_request_sampling_stays_on_calling_thread()
    test_model_client_request_sampling_restores_defaults_on_the_same_thread()
    print("ok")
