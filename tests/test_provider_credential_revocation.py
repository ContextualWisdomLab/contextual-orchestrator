"""Provider egress must fail closed when a KV credential disappears after validation."""

from __future__ import annotations

import socket
from unittest import mock

import pytest

from contextual_orchestrator import ModelAgent
from contextual_orchestrator.credentials import (
    InMemoryCredentialBackend,
    NotConfigured,
    set_backend,
)
from contextual_orchestrator.orchestrator import ModelClient


def _validated_provider() -> tuple[ModelClient, ModelAgent]:
    """Return a client with one public-address pin established under a live credential."""
    backend = InMemoryCredentialBackend()
    backend.set("MODEL_KEY", "sk-live-before-revocation")
    set_backend(backend)
    client = ModelClient()
    agent = ModelAgent(
        "remote_agent",
        "gpt-example",
        "https://provider.example/v1",
        "MODEL_KEY",
    )
    resolved = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))]
    with mock.patch(
        "contextual_orchestrator.orchestrator.socket.getaddrinfo",
        return_value=resolved,
    ):
        client._validate_provider(agent)
    return client, agent


def test_every_provider_egress_path_rechecks_revoked_credential() -> None:
    """Revocation after DNS validation must stop every request before socket egress."""
    client, agent = _validated_provider()
    try:
        set_backend(InMemoryCredentialBackend())
        operations = (
            lambda: client._send(agent, {"model": agent.model}),
            lambda: list(client._stream_send(agent, {"model": agent.model, "stream": True})),
            lambda: client._send_raw(agent, "responses", {"model": agent.model}),
            lambda: client._batch_upload(agent, b"{}\n"),
            lambda: client._batch_json(agent, "GET", "/batches/batch_1"),
            lambda: client._batch_raw(agent, "/files/file_1/content"),
        )
        for operation in operations:
            with mock.patch.object(
                client,
                "_open_provider",
                side_effect=AssertionError("provider egress attempted after credential revocation"),
            ):
                with pytest.raises(NotConfigured, match="resolvable credential"):
                    operation()
    finally:
        set_backend(None)


def test_provider_credential_resolution_returns_current_nonempty_secret() -> None:
    """The dispatch-time resolver returns the exact current registered secret value."""
    backend = InMemoryCredentialBackend()
    backend.set("MODEL_KEY", "sk-current-value")
    set_backend(backend)
    try:
        client = ModelClient()
        agent = ModelAgent(
            "remote_agent",
            "gpt-example",
            "https://provider.example/v1",
            "MODEL_KEY",
        )
        assert client._provider_credential(agent) == "sk-current-value"
    finally:
        set_backend(None)


def test_provider_credential_resolution_rejects_empty_secret() -> None:
    """An empty registered value is unavailable rather than an empty Bearer credential."""
    backend = InMemoryCredentialBackend()
    backend.set("MODEL_KEY", "")
    set_backend(backend)
    try:
        client = ModelClient()
        agent = ModelAgent(
            "remote_agent",
            "gpt-example",
            "https://provider.example/v1",
            "MODEL_KEY",
        )
        with pytest.raises(NotConfigured, match="resolvable credential"):
            client._provider_credential(agent)
    finally:
        set_backend(None)
