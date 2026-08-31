"""Durable, Valkey-managed state for batch-routing job registries.

Why this exists: every batch-routing job registry — the coordinator's
``job_id -> BatchJob`` map, the pg-llm-batch backends' tracked-request
maps, and the local backend's result stash — lived in per-process Python
dicts. A process restart between submit and retrieve silently discarded
every queued and completed job, turning ``GET /api/v1/batch_routing_jobs
/{id}/results`` into a 404 for work a caller already paid for. This
module lets those registries live in Valkey instead, so the queue
survives restarts and can be shared by more than one server process.

Design: :class:`ValkeyJsonMapping` is a ``MutableMapping[str, Any]``
backed by one Valkey hash, storing JSON documents. Dataclass values are
serialized with :func:`dataclasses.asdict`; a per-mapping ``decode``
callable rebuilds them on read. :func:`build_job_registry` returns a
factory that hands out either Valkey-backed mappings (when a Valkey URL
is configured and the ``redis`` client is importable) or plain dicts —
so every call site keeps identical mapping semantics and the default
deployment is unchanged.

The Valkey URL is deployment configuration with credentials, so it is
resolved through the KV credential registry
(``get_credential("batch_job_registry_valkey_url")``, with the config
store's secret surface as the injectable test fallback), never from
``os.getenv``.

The durable-row/registry split follows the transactional-outbox shape:
the durable record is the source of truth and the queue entry is only a
wake-up (Richardson, C. (2018). *Microservices patterns: With examples
in Java*. Manning; Kleppmann, M. (2017). *Designing data-intensive
applications*. O'Reilly).
"""

from __future__ import annotations

import dataclasses
import json
import threading
import time
import weakref
from collections.abc import MutableMapping
from contextlib import contextmanager
from typing import Any, Callable, Iterator, Optional

# Registry entries expire after this many seconds so abandoned jobs do
# not accumulate forever. Seven days comfortably outlives every batch
# backend's own completion window.
DEFAULT_RETENTION_SECONDS = 7 * 24 * 3600


class ClaimNotAcquired(RuntimeError):
    """Another worker owns a non-blocking durable job claim."""


class _ClaimLease:
    def __init__(
        self,
        claim: Any = None,
        *,
        lease_seconds: float | None = None,
        lost_ownership: threading.Event | None = None,
    ) -> None:
        self._claim = claim
        self._lease_seconds = lease_seconds
        self._lost_ownership = lost_ownership or threading.Event()

    def mark_lost(self) -> None:
        """Record that this worker can no longer prove claim ownership."""
        self._lost_ownership.set()

    def ensure_owned(self, *, refresh: bool = False) -> None:
        """Fail closed unless this worker still owns the durable claim."""
        if self._claim is None:
            return
        if self._lost_ownership.is_set():
            raise ClaimNotAcquired("durable job claim ownership was lost")
        try:
            if refresh:
                if self._lease_seconds is None:
                    raise ClaimNotAcquired("durable job claim lease is unavailable")
                retained = self._claim.extend(
                    self._lease_seconds,
                    replace_ttl=True,
                )
            else:
                retained = self._claim.owned()
        except Exception as exc:  # noqa: BLE001 - redis is optional.
            self.mark_lost()
            raise ClaimNotAcquired("durable job claim ownership is unavailable") from exc
        if not retained:
            self.mark_lost()
            raise ClaimNotAcquired("durable job claim ownership was lost")

    def atomic_identity(self) -> tuple[str, Any]:
        """Return the Valkey lock key and token for one atomic fenced write."""
        if self._claim is None:
            raise ClaimNotAcquired("durable job claim identity is unavailable")
        token = getattr(getattr(self._claim, "local", None), "token", None)
        name = getattr(self._claim, "name", None)
        if not name or token is None:
            self.mark_lost()
            raise ClaimNotAcquired("durable job claim identity is unavailable")
        return str(name), token


def _encode(value: Any) -> str:
    """Serialize one registry value (dataclasses included) to JSON."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        payload: Any = {"__dataclass__": True, "value": dataclasses.asdict(value)}
    elif isinstance(value, list) and value and all(
        dataclasses.is_dataclass(item) and not isinstance(item, type) for item in value
    ):
        payload = {"__dataclass_list__": True, "value": [dataclasses.asdict(item) for item in value]}
    else:
        payload = {"value": value}
    return json.dumps(payload, ensure_ascii=False)


class ValkeyJsonMapping(MutableMapping):
    """One named registry stored as JSON documents in a Valkey hash.

    ``decode`` rebuilds rich values (for example dataclasses) from the
    stored JSON dict; when omitted, values come back as plain JSON data.
    Reads and writes go straight to Valkey — there is no local cache —
    so every process sharing the URL sees one consistent registry.
    """

    def __init__(
        self,
        client: Any,
        name: str,
        *,
        decode: Optional[Callable[[Any], Any]] = None,
        retention_seconds: int = DEFAULT_RETENTION_SECONDS,
    ) -> None:
        self._client = client
        self._key = f"batch_job_registry:{name}"
        self._decode = decode
        self._retention_seconds = retention_seconds

    def _decode_document(self, raw: Any) -> Any:
        document = json.loads(raw)
        value = document["value"]
        if self._decode is None:
            return value
        if document.get("__dataclass_list__"):
            return [self._decode(item) for item in value]
        if document.get("__dataclass__"):
            return self._decode(value)
        return value

    def __getitem__(self, job_id: str) -> Any:
        raw = self._client.hget(self._key, job_id)
        if raw is None:
            raise KeyError(job_id)
        # Reads refresh retention too: a registry that is only polled
        # after submission must not expire mid-use.
        self._client.expire(self._key, self._retention_seconds)
        return self._decode_document(raw)

    def __setitem__(self, job_id: str, value: Any) -> None:
        self._client.hset(self._key, job_id, _encode(value))
        # Retention is per-registry: any write pushes the whole hash's
        # expiry forward, so an active registry never expires mid-flight.
        self._client.expire(self._key, self._retention_seconds)

    def set_if_absent(self, job_id: str, value: Any) -> bool:
        """Store one value only when no concurrent writer stored it first."""
        created = bool(self._client.hsetnx(self._key, job_id, _encode(value)))
        if created:
            self._client.expire(self._key, self._retention_seconds)
        return created

    def __delitem__(self, job_id: str) -> None:
        if not self._client.hdel(self._key, job_id):
            raise KeyError(job_id)

    def __iter__(self) -> Iterator[str]:
        for field_name in self._client.hkeys(self._key):
            yield field_name.decode() if isinstance(field_name, bytes) else str(field_name)

    def __len__(self) -> int:
        return int(self._client.hlen(self._key))


class JobRegistryFactory:
    """Hands out named job registries, Valkey-backed when configured."""

    def __init__(self, client: Any = None, *, retention_seconds: int = DEFAULT_RETENTION_SECONDS) -> None:
        self._client = client
        self._retention_seconds = retention_seconds
        self._local_locks: weakref.WeakValueDictionary[str, threading.Lock] = (
            weakref.WeakValueDictionary()
        )
        self._local_locks_guard = threading.Lock()

    def lock(
        self,
        name: str,
        key: str,
        *,
        lease_seconds: float | None = None,
        renew_until_epoch: float | None = None,
    ):
        """Return an atomic shard claim with bounded lease and acquisition wait."""
        lock_name = f"batch_job_registry:{name}:claim:{key}"
        if self._client is not None:
            if lease_seconds is None or lease_seconds <= 0:
                raise ValueError("durable claim lease_seconds must be positive")
            claim = self._client.lock(
                lock_name,
                timeout=lease_seconds,
                blocking=True,
                blocking_timeout=lease_seconds,
                thread_local=False,
            )

            @contextmanager
            def acquired_claim():
                if not claim.acquire():
                    raise ClaimNotAcquired(lock_name)
                stop_renewal = threading.Event()
                lost_ownership = threading.Event()
                lease = _ClaimLease(
                    claim,
                    lease_seconds=lease_seconds,
                    lost_ownership=lost_ownership,
                )
                renewal_thread = None
                if renew_until_epoch is not None:

                    def renew_claim() -> None:
                        interval = max(0.05, min(lease_seconds / 3, 1.0))
                        while not stop_renewal.wait(interval):
                            remaining = renew_until_epoch - time.time()
                            if remaining <= 0:
                                lease.mark_lost()
                                return
                            try:
                                # redis-py's Lock.extend script checks the
                                # claim token before replacing the TTL (CAS).
                                renewed = claim.extend(
                                    max(0.05, min(lease_seconds, remaining)),
                                    replace_ttl=True,
                                )
                                if not renewed:
                                    lease.mark_lost()
                                    return
                            except Exception:  # noqa: BLE001 - redis is optional.
                                lease.mark_lost()
                                return

                    renewal_thread = threading.Thread(
                        target=renew_claim,
                        name="job-claim-renewal",
                        daemon=True,
                    )
                    renewal_thread.start()
                try:
                    yield lease
                finally:
                    stop_renewal.set()
                    if renewal_thread is not None:
                        renewal_thread.join()
                    try:
                        claim.release()
                    except Exception as exc:  # noqa: BLE001 - redis is optional.
                        if renew_until_epoch is None or type(exc).__name__ != "LockNotOwnedError":
                            raise

            return acquired_claim()
        with self._local_locks_guard:
            lock = self._local_locks.get(lock_name)
            if lock is None:
                lock = threading.Lock()
                self._local_locks[lock_name] = lock

            @contextmanager
            def acquired_local_claim():
                with lock:
                    yield _ClaimLease()

        return acquired_local_claim()

    def publish_provider_embedding_terminal(
        self,
        claim: _ClaimLease,
        job_id: str,
        *,
        status: str,
        results: Any = None,
        usage: Any = None,
        error: Any = None,
    ) -> None:
        """Atomically publish one durable terminal state while its claim is owned."""
        if self._client is None:
            raise RuntimeError("atomic terminal publication requires a durable registry")
        if status not in {"completed", "failed"}:
            raise ValueError("terminal status must be completed or failed")
        lock_name, token = claim.atomic_identity()
        script = """
        if redis.call('get', KEYS[1]) ~= ARGV[1] then return 0 end
        local current = redis.call('hget', KEYS[2], ARGV[2])
        if current ~= ARGV[3] and current ~= ARGV[4] then return 0 end
        if ARGV[6] ~= '' then redis.call('hset', KEYS[3], ARGV[2], ARGV[6]) end
        if ARGV[7] ~= '' then redis.call('hset', KEYS[4], ARGV[2], ARGV[7]) end
        if ARGV[8] ~= '' then redis.call('hset', KEYS[5], ARGV[2], ARGV[8]) end
        redis.call('hset', KEYS[2], ARGV[2], ARGV[5])
        for index = 2, 5 do redis.call('expire', KEYS[index], ARGV[9]) end
        return 1
        """
        published = self._client.eval(
            script,
            5,
            lock_name,
            "batch_job_registry:provider_embedding_states",
            "batch_job_registry:provider_embedding_results",
            "batch_job_registry:provider_embedding_usage",
            "batch_job_registry:provider_embedding_errors",
            token,
            job_id,
            _encode("running"),
            _encode("queued"),
            _encode(status),
            "" if results is None else _encode(results),
            "" if usage is None else _encode(usage),
            "" if error is None else _encode(error),
            self._retention_seconds,
        )
        if not published:
            claim.mark_lost()
            raise ClaimNotAcquired("durable job claim ownership was lost before publication")

    @property
    def durable(self) -> bool:
        """True when registries survive a process restart."""
        return self._client is not None

    @property
    def retention_seconds(self) -> int:
        """Return the configured terminal-result retention contract."""
        return self._retention_seconds

    def mapping(self, name: str, *, decode: Optional[Callable[[Any], Any]] = None) -> MutableMapping:
        """Return the registry called ``name`` — a dict unless Valkey is configured."""
        if self._client is None:
            return {}
        return ValkeyJsonMapping(
            self._client, name, decode=decode, retention_seconds=self._retention_seconds
        )


def build_job_registry(config_store: Any) -> JobRegistryFactory:
    """Build the registry factory from the config store's secret surface.

    Resolves ``batch_job_registry_valkey_url`` through the KV credential
    registry first, then the config store's secret surface (the injectable
    test path). When it is unset,
    or the ``redis`` client package is not installed (it ships in the
    ``queue`` extra), registries stay in-process dicts — exactly the
    pre-Valkey behavior — so nothing changes for deployments that have
    not opted in.
    """
    from .credentials import get_credential

    try:
        url = get_credential("batch_job_registry_valkey_url")
    except Exception:  # noqa: BLE001 - no credential backend configured
        url = None
    if not url:
        get_secret = getattr(config_store, "get_secret", None)
        url = get_secret("batch_job_registry_valkey_url", None) if callable(get_secret) else None
    if not url:
        return JobRegistryFactory(None)
    try:
        import redis
    except ImportError:
        return JobRegistryFactory(None)
    client = redis.Redis.from_url(str(url))
    retention = DEFAULT_RETENTION_SECONDS
    get = getattr(config_store, "get", None)
    if callable(get):
        configured = get("routing", "batch_job_retention_seconds", DEFAULT_RETENTION_SECONDS)
        if type(configured) is int and configured >= 1:
            retention = configured
    return JobRegistryFactory(client, retention_seconds=retention)
