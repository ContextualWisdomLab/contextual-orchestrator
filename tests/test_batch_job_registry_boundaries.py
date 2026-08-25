"""Boundary tests for Valkey-backed batch job registry construction."""

from __future__ import annotations

import sys
import types
from dataclasses import dataclass

from contextual_orchestrator.batch_job_registry import (
    DEFAULT_RETENTION_SECONDS,
    JobRegistryFactory,
    ValkeyJsonMapping,
    build_job_registry,
)
from contextual_orchestrator.credentials import set_backend


@dataclass(frozen=True)
class _TrackedRequest:
    request_id: str


class _FakeValkey:
    """Minimal hash client standing in for redis/valkey."""

    def __init__(self) -> None:
        self.hash: dict[str, str] = {}
        self.ttls: list[int] = []

    def hget(self, key: str, field: str) -> str | None:
        return self.hash.get(field)

    def hset(self, key: str, field: str, value: str) -> int:
        self.hash[field] = value
        return 1

    def hdel(self, key: str, field: str) -> int:
        return 1 if self.hash.pop(field, None) is not None else 0

    def hkeys(self, key: str) -> list[str]:
        return sorted(self.hash)

    def hlen(self, key: str) -> int:
        return len(self.hash)

    def expire(self, key: str, seconds: int) -> bool:
        self.ttls.append(seconds)
        return True


def test_decode_omitted_flag_returns_plain_value_without_decoding() -> None:
    client = _FakeValkey()
    decoded: list[object] = []

    def decode(value: object) -> object:
        decoded.append(value)
        return value

    mapping = ValkeyJsonMapping(client, "plain_decode", decode=decode)
    mapping["job_plain"] = {"raw": "document"}
    assert mapping["job_plain"] == {"raw": "document"}
    # The registered decoder must not run for non-dataclass documents.
    assert decoded == []


def test_build_falls_back_to_config_secret_when_credential_backend_raises(
    monkeypatch,
) -> None:
    # An unknown KV backend selector makes get_credential raise NotConfigured;
    # registry construction must degrade to the config store secret surface.
    monkeypatch.setenv("CONTEXTUAL_ORCHESTRATOR_KV_BACKEND", "vault")
    set_backend(None)
    try:

        class SecretStore:
            @staticmethod
            def get_secret(name: str, default: object) -> object:
                assert name == "batch_job_registry_valkey_url"
                return "redis://registry_user@localhost:6379/0"

        class FakeRedisModule:
            class Redis:
                calls: list[str] = []

                @classmethod
                def from_url(cls, url: str) -> object:
                    cls.calls.append(url)
                    return _FakeValkey()

        fake_module = types.ModuleType("redis")
        fake_module.Redis = FakeRedisModule.Redis  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "redis", fake_module)

        factory = build_job_registry(SecretStore())
        assert factory.durable
        assert FakeRedisModule.Redis.calls == [
            "redis://registry_user@localhost:6379/0"
        ]
    finally:
        set_backend(None)


def test_build_prefers_credential_registry_url_without_config_lookup(
    monkeypatch,
) -> None:
    from contextual_orchestrator.credentials import register_credential

    set_backend(None)  # selector defaults to the in-memory backend
    try:
        register_credential(
            "batch_job_registry_valkey_url", "valkey://queue_user@localhost:6379/9"
        )

        class ProbingStore:  # must never be consulted for secrets
            def get_secret(self, name: str, default: object) -> object:
                raise AssertionError("config secret surface must not be queried")

            def get(self, section: str, name: str, default: int) -> int:
                return default

        _install_fake_redis(monkeypatch)
        factory = build_job_registry(ProbingStore())
        assert factory.durable
    finally:
        set_backend(None)


def test_build_ignores_non_callable_secret_surface() -> None:
    class BrokenSecretStore:  # get_secret exists but is not callable
        get_secret = "not-callable"

    factory = build_job_registry(BrokenSecretStore())
    assert isinstance(factory, JobRegistryFactory)
    assert not factory.durable


def _install_fake_redis(monkeypatch) -> types.ModuleType:
    fake_module = types.ModuleType("redis")

    class Redis:
        @classmethod
        def from_url(cls, url: str) -> _FakeValkey:
            return _FakeValkey()

    fake_module.Redis = Redis  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "redis", fake_module)
    return fake_module


def test_build_honors_configured_positive_retention(monkeypatch) -> None:
    class ConfigStore:
        @staticmethod
        def get_secret(name: str, default: object) -> object:
            return "valkey://queue_user@localhost:6379/2"

        @staticmethod
        def get(_section: str, _name: str, default: int) -> int:
            assert default == DEFAULT_RETENTION_SECONDS
            return 3600

    _install_fake_redis(monkeypatch)
    factory = build_job_registry(ConfigStore())
    assert factory.durable
    client = _FakeValkey()
    mapping = factory.mapping("retention_probe")
    assert isinstance(mapping, ValkeyJsonMapping)
    assert mapping._retention_seconds == 3600
    del client


def test_build_rejects_zero_and_non_integer_retention(monkeypatch) -> None:
    class ZeroRetention:
        @staticmethod
        def get_secret(name: str, default: object) -> object:
            return "valkey://queue_user@localhost:6379/3"

        @staticmethod
        def get(_section: str, _name: str, default: int) -> int:
            return 0

    _install_fake_redis(monkeypatch)
    factory = build_job_registry(ZeroRetention())
    mapping = factory.mapping("zero_probe")
    assert mapping._retention_seconds == DEFAULT_RETENTION_SECONDS  # type: ignore[attr-defined]

    class FloatRetention(ZeroRetention):
        @staticmethod
        def get(_section: str, _name: str, default: int) -> float:
            return 900.5

    factory_float = build_job_registry(FloatRetention())
    mapping_float = factory_float.mapping("float_probe")
    assert mapping_float._retention_seconds == DEFAULT_RETENTION_SECONDS  # type: ignore[attr-defined]


def test_build_defaults_when_redis_package_missing(
    monkeypatch,
) -> None:
    class UrlOnly:
        @staticmethod
        def get_secret(name: str, default: object) -> object:
            return "valkey://queue_user@localhost:6379/4"

    real_import = __import__

    def blocked(name: str, *args: object, **kwargs: object) -> object:
        if name == "redis":
            raise ImportError("redis unavailable")
        return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr("builtins.__import__", blocked)
    factory = build_job_registry(UrlOnly())
    assert isinstance(factory, JobRegistryFactory)
    assert not factory.durable
