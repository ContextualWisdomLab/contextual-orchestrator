"""Optional response-cache providers for standalone and distributed deployments."""

from __future__ import annotations

from collections.abc import Mapping
import copy
import hashlib
import json
from typing import Any, Protocol


class ResponseCacheProvider(Protocol):
    """Small provider contract shared by local and Redis-compatible caches."""

    def get(self, key: str) -> dict[str, Any] | None:
        """Return a cached response or ``None`` when it is absent or unusable."""

    def put(self, key: str, value: Mapping[str, Any]) -> None:
        """Store one response for the provider's configured lifetime."""


def build_response_cache_key(
    messages: list[Mapping[str, Any]],
    mode: str,
    *,
    model: str = "contextual-orchestrator",
    parameters: Mapping[str, Any] | None = None,
) -> str:
    """Build a deterministic key from the semantic request envelope.

    Message order and content are meaningful; mapping key order is not. A digest
    keeps prompts and user data out of Redis keys while avoiding false hits across
    models or orchestration modes.
    """
    payload = json.dumps(
        {
            "model": model,
            "mode": mode,
            "messages": messages,
            "parameters": dict(parameters or {}),
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class RedisResponseCacheProvider:
    """Use a Redis/Dragonfly-compatible client without a runtime dependency.

    The caller supplies an already configured client (for example ``redis.Redis``
    or a Dragonfly-compatible client). Cache read/write errors fail open so a
    cache outage cannot turn a valid provider request into an application outage.
    """

    def __init__(self, client: Any, ttl_seconds: int, namespace: str = "contextual_orchestrator_response") -> None:
        if not callable(getattr(client, "get", None)) or not callable(getattr(client, "set", None)):
            raise TypeError("client must provide get and set methods")
        if isinstance(ttl_seconds, bool) or type(ttl_seconds) is not int or ttl_seconds < 1:
            raise ValueError("ttl_seconds must be a positive integer")
        if not isinstance(namespace, str) or not namespace.strip():
            raise ValueError("namespace must be a non-empty string")
        self.client = client
        self.ttl_seconds = ttl_seconds
        self.namespace = namespace.strip()

    def _storage_key(self, key: str) -> str:
        """Prefix a digest key so unrelated applications share no cache namespace."""
        if not isinstance(key, str) or not key:
            raise ValueError("cache key must be a non-empty string")
        return f"{self.namespace}:{key}"

    def get(self, key: str) -> dict[str, Any] | None:
        """Read and validate one JSON response, failing open on backend errors."""
        storage_key = self._storage_key(key)
        try:
            raw = self.client.get(storage_key)
            if raw is None:
                return None
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            value = json.loads(raw) if isinstance(raw, str) else raw
            return copy.deepcopy(dict(value)) if isinstance(value, Mapping) else None
        except Exception:  # noqa: BLE001 - optional cache must fail open
            return None

    def put(self, key: str, value: Mapping[str, Any]) -> None:
        """Write one JSON response with the configured TTL, failing open on errors."""
        if not isinstance(value, Mapping):
            raise TypeError("cached value must be a mapping")
        storage_key = self._storage_key(key)
        try:
            self.client.set(
                storage_key,
                json.dumps(dict(value), ensure_ascii=False, separators=(",", ":")),
                ex=self.ttl_seconds,
            )
        except Exception:  # noqa: BLE001 - optional cache must fail open
            return
