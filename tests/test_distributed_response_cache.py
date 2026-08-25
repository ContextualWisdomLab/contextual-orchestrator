"""Distributed response-cache provider and bypass behavior."""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from contextual_orchestrator import (
    ModelAgent,
    RedisResponseCacheProvider,
    TaskOrchestrator,
    build_response_cache_key,
)
from contextual_orchestrator.server import RequestError, _cache_bypass_header
from contextual_orchestrator.orchestrator import ModelClient


class _FakeRedis:
    """Small Redis/Dragonfly-compatible fake that records TTL writes."""

    def __init__(self) -> None:
        self.values: dict[str, object] = {}
        self.expirations: dict[str, int] = {}
        self.get_calls = 0
        self.set_calls = 0
        self.fail_get = False
        self.fail_set = False

    def get(self, key: str) -> object:
        self.get_calls += 1
        if self.fail_get:
            raise ConnectionError("cache unavailable")
        return self.values.get(key)

    def set(self, key: str, value: str, *, ex: int) -> bool:
        self.set_calls += 1
        if self.fail_set:
            raise ConnectionError("cache unavailable")
        self.values[key] = value
        self.expirations[key] = ex
        return True


class _CountingClient:
    """Return a deterministic mock completion while counting provider calls."""

    def __init__(self) -> None:
        from contextual_orchestrator.orchestrator import ModelClient

        self._client = ModelClient()
        self.calls = 0

    def chat(self, agent: ModelAgent, messages: list, temperature: float = 0.2) -> str:
        self.calls += 1
        return self._client.chat(agent, messages, temperature)

    def take_usage(self) -> dict | None:
        return self._client.take_usage()


class _BrokenCache:
    """Failing custom provider used to prove cache outages do not fail requests."""

    def get(self, key: str) -> dict | None:
        raise ConnectionError("cache unavailable")

    def put(self, key: str, value: dict) -> None:
        raise ConnectionError("cache unavailable")


def test_key_is_order_stable_but_model_and_mode_specific() -> None:
    messages = [{"role": "user", "content": "same"}]
    reordered = [{"content": "same", "role": "user"}]
    assert build_response_cache_key(messages, "route") == build_response_cache_key(reordered, "route")
    assert build_response_cache_key(messages, "route") != build_response_cache_key(messages, "conduct")
    assert build_response_cache_key(messages, "route", model="model_a") != build_response_cache_key(
        messages, "route", model="model_b"
    )
    assert build_response_cache_key(messages, "route", parameters={"temperature": 0.1}) != build_response_cache_key(
        messages, "route", parameters={"temperature": 0.9}
    )
    assert build_response_cache_key(messages, "route", partition="principal-a") != build_response_cache_key(
        messages, "route", partition="principal-b"
    )
    with pytest.raises(ValueError, match="partition"):
        build_response_cache_key(messages, "route", partition=" ")


def test_request_scoped_sampling_produces_thread_isolated_cache_keys() -> None:
    client = ModelClient(temperature=0.4)
    orchestrator = TaskOrchestrator(
        [ModelAgent("general_agent", "mock", tags=("reasoning", "writing"))],
        client=client,
    )
    messages = [{"role": "user", "content": "same prompt"}]
    barrier = threading.Barrier(2)

    def cache_key(temperature: float) -> str:
        with client.request_settings(temperature=temperature):
            barrier.wait()
            return orchestrator._cache_key(messages, "route")

    with ThreadPoolExecutor(max_workers=2) as executor:
        keys = list(executor.map(cache_key, (0.1, 0.9)))

    assert keys[0] != keys[1]
    assert client.request_settings_snapshot()["temperature"] == 0.4


def test_redis_compatible_provider_round_trips_json_with_ttl_and_namespace() -> None:
    client = _FakeRedis()
    provider = RedisResponseCacheProvider(client, ttl_seconds=3600, namespace="gateway")
    provider.put("digest", {"answer": "cached", "trace": []})
    assert client.expirations == {"gateway:digest": 3600}
    assert provider.get("digest") == {"answer": "cached", "trace": []}

    client.values["gateway:bytes"] = json.dumps({"answer": "bytes"}).encode()
    assert provider.get("bytes") == {"answer": "bytes"}


def test_provider_rejects_invalid_configuration_and_payloads() -> None:
    with pytest.raises(TypeError, match="get and set"):
        RedisResponseCacheProvider(object(), 60)
    with pytest.raises(ValueError, match="positive integer"):
        RedisResponseCacheProvider(_FakeRedis(), 0)
    with pytest.raises(ValueError, match="namespace"):
        RedisResponseCacheProvider(_FakeRedis(), 60, " ")

    provider = RedisResponseCacheProvider(_FakeRedis(), 60)
    with pytest.raises(ValueError, match="cache key"):
        provider.get("")
    with pytest.raises(TypeError, match="mapping"):
        provider.put("key", [])  # type: ignore[arg-type]


def test_backend_errors_and_malformed_values_fail_open() -> None:
    client = _FakeRedis()
    provider = RedisResponseCacheProvider(client, 60)
    client.values["contextual_orchestrator_response:bad"] = "not-json"
    assert provider.get("bad") is None
    client.fail_get = True
    assert provider.get("anything") is None
    client.fail_get = False
    client.fail_set = True
    provider.put("anything", {"answer": "live path remains available"})


def test_semantically_malformed_cached_response_is_ignored() -> None:
    client = _CountingClient()
    redis = _FakeRedis()
    provider = RedisResponseCacheProvider(redis, 60)
    orchestrator = TaskOrchestrator(
        [ModelAgent("general_agent", "mock", tags=("reasoning", "writing"))],
        client=client,
        cache_provider=provider,
    )
    messages = [{"role": "user", "content": "recover from stale cache"}]
    key = orchestrator._cache_key(messages, "auto")
    redis.values[f"contextual_orchestrator_response:{key}"] = json.dumps({"answer": "stale"})

    result = orchestrator.complete(messages)

    assert result["answer"] != "stale"
    assert client.calls == 1


def test_custom_cache_provider_errors_fail_open() -> None:
    orchestrator = TaskOrchestrator(
        [ModelAgent("general_agent", "mock", tags=("reasoning", "writing"))],
        client=_CountingClient(),
        cache_provider=_BrokenCache(),
    )

    result = orchestrator.complete([{"role": "user", "content": "live response"}])

    assert result["answer"]


def test_orchestrator_uses_distributed_cache_and_honors_bypass() -> None:
    client = _CountingClient()
    redis = _FakeRedis()
    orchestrator = TaskOrchestrator(
        [ModelAgent("general_agent", "mock", tags=("reasoning", "writing"))],
        client=client,
        cache_provider=RedisResponseCacheProvider(redis, 60),
    )
    messages = [{"role": "user", "content": "identical request"}]
    first = orchestrator.complete(messages)
    assert first["answer"]
    calls_after_first = client.calls
    second = orchestrator.complete(messages)
    assert second["answer"] == first["answer"]
    assert second["trace"] == first["trace"]
    assert first["cache_status"] == "miss"
    assert second["cache_status"] == "hit"
    assert client.calls == calls_after_first
    changed_model = orchestrator.complete(messages, model_name="another-model")
    assert changed_model["cache_status"] == "miss"
    assert client.calls > calls_after_first
    calls_after_model_change = client.calls
    bypassed = orchestrator.complete(messages, bypass_cache=True)
    assert bypassed["answer"]
    assert client.calls > calls_after_model_change


@pytest.mark.parametrize("value", [None, "", "false", "0", "TRUE", "1"])
def test_cache_bypass_header_accepts_explicit_boolean_values(value: str | None) -> None:
    assert _cache_bypass_header(value) is (value is not None and value.strip().lower() in {"true", "1"})


def test_cache_bypass_header_rejects_ambiguous_values() -> None:
    with pytest.raises(RequestError, match="X-Cache-Bypass"):
        _cache_bypass_header("maybe")
