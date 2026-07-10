"""Exact-match response caching — the biggest cost lever for a model gateway.

A repeat identical request must not pay a second provider call. These assert the
cache hit skips the provider, TTL expiry and LRU eviction work, cached entries are
mutation-isolated, and the default (disabled) path calls through every time.
"""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.orchestrator import ModelClient, _ResponseCache  # noqa: E402


class _CountingClient(ModelClient):
    """Counts provider calls; delegates to the deterministic mock path."""

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def chat(self, agent: ModelAgent, messages: list, temperature: float = 0.2) -> str:  # type: ignore[override]
        self.calls += 1
        return super().chat(agent, messages, temperature)


def _orch(client: _CountingClient, cache_ttl: float = 0.0) -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock", tags=("reasoning", "writing"))],
        client=client,
        cache_ttl=cache_ttl,
    )


def test_cache_hit_skips_provider_call() -> None:
    client = _CountingClient()
    orchestrator = _orch(client, cache_ttl=60)
    messages = [{"role": "user", "content": "identical request"}]

    first = orchestrator.complete(messages)
    calls_after_first = client.calls
    assert calls_after_first >= 1

    second = orchestrator.complete(messages)
    assert client.calls == calls_after_first  # served from cache, no new provider call
    assert second == first


def test_different_request_is_not_a_hit() -> None:
    client = _CountingClient()
    orchestrator = _orch(client, cache_ttl=60)
    orchestrator.complete([{"role": "user", "content": "one"}])
    after_one = client.calls
    orchestrator.complete([{"role": "user", "content": "two"}])
    assert client.calls > after_one  # distinct payload -> distinct key -> provider called


def test_disabled_by_default_calls_through_every_time() -> None:
    client = _CountingClient()
    orchestrator = _orch(client)  # cache_ttl defaults to 0 (disabled)
    assert orchestrator._cache is None
    messages = [{"role": "user", "content": "same"}]
    orchestrator.complete(messages)
    after_first = client.calls
    orchestrator.complete(messages)
    assert client.calls > after_first  # no cache: provider hit again


def test_ttl_expiry_evicts() -> None:
    now = [100.0]
    cache = _ResponseCache(ttl=10, max_entries=8, clock=lambda: now[0])
    cache.put("k", {"answer": "cached"})
    assert cache.get("k") == {"answer": "cached"}
    now[0] = 111.0  # 11s later, past the 10s ttl
    assert cache.get("k") is None


def test_lru_eviction_when_full() -> None:
    now = [0.0]
    cache = _ResponseCache(ttl=1000, max_entries=2, clock=lambda: now[0])
    cache.put("a", {"v": 1})
    cache.put("b", {"v": 2})
    cache.get("a")  # touch "a" so "b" is now least-recently used
    cache.put("c", {"v": 3})  # over capacity -> evict "b"
    assert cache.get("b") is None
    assert cache.get("a") == {"v": 1}
    assert cache.get("c") == {"v": 3}


def test_cached_entry_is_mutation_isolated() -> None:
    cache = _ResponseCache(ttl=1000)
    cache.put("k", {"trace": [1]})
    got = cache.get("k")
    got["trace"].append(2)  # caller mutates the returned copy
    assert cache.get("k") == {"trace": [1]}  # cache master copy is untouched


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
    print("ok")
