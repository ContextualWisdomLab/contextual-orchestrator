"""Edge-case coverage for bounded DNS pinning in the NIM credential broker."""

from __future__ import annotations

import socket
from typing import Any

import pytest

from scripts.ci import nim_credential_broker as broker


def _ipv4_record(address: str) -> tuple[Any, ...]:
    """Build one IPv4 ``getaddrinfo`` record for deterministic resolver tests."""

    return (
        socket.AF_INET,
        socket.SOCK_STREAM,
        socket.IPPROTO_TCP,
        "",
        (address, broker.UPSTREAM_PORT),
    )


def test_public_address_snapshot_rejects_excessive_global_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A large global answer set cannot amplify credential-bearing retries."""

    monkeypatch.setattr(
        broker.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            _ipv4_record(f"8.8.8.{index}")
            for index in range(1, broker.MAX_UPSTREAM_ADDRESSES + 2)
        ],
    )

    with pytest.raises(OSError, match="too many addresses"):
        broker._validated_public_addresses(  # noqa: SLF001 - security contract.
            broker.UPSTREAM_HOST,
            broker.UPSTREAM_PORT,
        )


def test_default_broker_hides_invalid_resolver_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Malformed DNS evidence fails closed without exposing resolver detail."""

    monkeypatch.setattr(
        broker,
        "_validated_public_addresses",
        lambda *_args: (_ for _ in ()).throw(ValueError("malformed address detail")),
    )
    application = broker.NIMCredentialBroker("top-secret")

    response = application.handle("GET", "/v1/models", {}, b"")

    assert response.status == 502
    assert b"malformed address" not in response.body
    assert b"top-secret" not in response.body
