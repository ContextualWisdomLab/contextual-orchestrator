"""Provider sampling-parameter compatibility policy.

The orchestration layer must not invent a sampling value for a provider request.
Some capability-constrained deployments accept only their provider default and
reject an otherwise harmless explicit value. This module installs a narrow
transport policy on :class:`ModelClient`: an omitted client-level temperature
stays omitted, while an explicitly configured or request-scoped value is
preserved exactly.
"""

from __future__ import annotations

import functools
import json
from typing import Any, Iterable

_MISSING = object()
_INSTALLATION_MARKER = "_sampling_contract_installed"


def _without_null_temperature(payload: dict[str, Any]) -> dict[str, Any]:
    """Return *payload* without an explicitly null temperature field."""
    if payload.get("temperature", _MISSING) is not None:
        return payload
    sanitized = dict(payload)
    sanitized.pop("temperature", None)
    return sanitized


def _without_null_batch_temperatures(payload: bytes) -> bytes:
    """Remove null temperatures from internally generated Batch API JSONL."""
    sanitized_lines: list[str] = []
    for raw_line in payload.decode("utf-8").splitlines():
        record = json.loads(raw_line)
        body = record.get("body")
        if isinstance(body, dict):
            record = dict(record)
            record["body"] = _without_null_temperature(body)
        sanitized_lines.append(json.dumps(record, ensure_ascii=False))
    return "\n".join(sanitized_lines).encode("utf-8")


def install_sampling_contract(model_client_class: type[Any]) -> None:
    """Install omit-by-default temperature handling on one ModelClient class.

    Installation is idempotent so package reloads and test doubles cannot stack
    wrappers. The original public methods remain responsible for retries,
    provider validation, streaming, and batch lifecycle behavior.
    """
    if getattr(model_client_class, _INSTALLATION_MARKER, False):
        return

    original_init = model_client_class.__init__
    original_send_with_retry = model_client_class._send_with_retry
    original_stream_send = model_client_class._stream_send
    original_batch_upload = model_client_class._batch_upload

    @functools.wraps(original_init)
    def initialize(
        self: Any,
        timeout: int = 90,
        max_output_tokens: int = 2048,
        max_retries: int = 2,
        local_max_retries: int = 0,
        retry_backoff: float = 0.5,
        retry_backoff_cap: float = 8.0,
        temperature: float | None = None,
        local_concurrency: int = 1,
        ca_bundle: str | None = None,
        verify_tls: bool = True,
        allowed_provider_hosts: Iterable[str] | None = None,
    ) -> None:
        original_init(
            self,
            timeout=timeout,
            max_output_tokens=max_output_tokens,
            max_retries=max_retries,
            local_max_retries=local_max_retries,
            retry_backoff=retry_backoff,
            retry_backoff_cap=retry_backoff_cap,
            temperature=temperature,
            local_concurrency=local_concurrency,
            ca_bundle=ca_bundle,
            verify_tls=verify_tls,
            allowed_provider_hosts=allowed_provider_hosts,
        )
        self.default_temperature = temperature
        self.temperature = temperature

    @functools.wraps(original_send_with_retry)
    def send_with_retry(
        self: Any,
        agent: Any,
        payload: dict[str, Any],
        destination: Any = None,
        *,
        timeout: float | None = None,
    ) -> str:
        return original_send_with_retry(
            self,
            agent,
            _without_null_temperature(payload),
            destination,
            timeout=timeout,
        )

    @functools.wraps(original_stream_send)
    def stream_send(
        self: Any,
        agent: Any,
        payload: dict[str, Any],
        destination: Any = None,
    ) -> Any:
        return original_stream_send(
            self,
            agent,
            _without_null_temperature(payload),
            destination,
        )

    @functools.wraps(original_batch_upload)
    def batch_upload(
        self: Any,
        agent: Any,
        payload: bytes,
        destination: Any = None,
    ) -> str:
        return original_batch_upload(
            self,
            agent,
            _without_null_batch_temperatures(payload),
            destination,
        )

    model_client_class.__init__ = initialize
    model_client_class._send_with_retry = send_with_retry
    model_client_class._stream_send = stream_send
    model_client_class._batch_upload = batch_upload
    setattr(model_client_class, _INSTALLATION_MARKER, True)
