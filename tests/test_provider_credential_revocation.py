"""Provider egress must fail closed when a KV credential disappears after validation."""

from __future__ import annotations

import http.client
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
from contextual_orchestrator.provider_transport import _PinnedHTTPSConnection


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


def test_every_provider_egress_path_blocks_revoked_credential_before_socket() -> None:
    """Revocation after DNS validation must stop every HTTPS request before socket egress."""
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
            with mock.patch(
                "contextual_orchestrator.provider_transport.socket.create_connection",
                side_effect=AssertionError("socket egress attempted after credential revocation"),
            ):
                with pytest.raises(NotConfigured, match="Bearer credential"):
                    operation()
    finally:
        set_backend(None)


def test_pinned_connection_rejects_missing_authorization_before_super_request() -> None:
    """A direct pinned request without provider authorization also fails closed."""
    connection = _PinnedHTTPSConnection(
        "provider.example",
        "8.8.8.8",
        443,
        1.0,
        mock.Mock(),
    )
    with mock.patch.object(http.client.HTTPSConnection, "request") as base_request:
        with pytest.raises(NotConfigured, match="Bearer credential"):
            connection.request("POST", "/v1/chat/completions", headers={})
    base_request.assert_not_called()


def test_pinned_connection_accepts_nonempty_bearer_for_normal_dispatch() -> None:
    """A current non-empty Bearer value reaches the standard HTTPS request machinery."""
    connection = _PinnedHTTPSConnection(
        "provider.example",
        "8.8.8.8",
        443,
        1.0,
        mock.Mock(),
    )
    headers = {"Authorization": "Bearer sk-current-value"}
    with mock.patch.object(http.client.HTTPSConnection, "request") as base_request:
        connection.request("POST", "/v1/chat/completions", headers=headers)
    base_request.assert_called_once_with(
        "POST",
        "/v1/chat/completions",
        body=None,
        headers=headers,
        encode_chunked=False,
    )
