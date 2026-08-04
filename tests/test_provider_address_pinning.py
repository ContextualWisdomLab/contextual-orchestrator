"""Regression tests for DNS-pinned provider connections."""

from __future__ import annotations

import ssl
import urllib.error
import urllib.request
from unittest import mock

import pytest

from contextual_orchestrator import ModelAgent
from contextual_orchestrator.credentials import InMemoryCredentialBackend, set_backend
from contextual_orchestrator.orchestrator import ModelClient
from contextual_orchestrator.provider_transport import (
    _PinnedHTTPSConnection,
    _ProviderHTTPResponse,
    _validated_public_addresses,
    install_provider_transport,
)


class _FakeResponse:
    """Observable provider response double."""

    def __init__(self, status: int = 200, body: bytes = b"ok") -> None:
        """Initialize status, content, headers, and cleanup state."""
        self.status = status
        self.reason = "provider status"
        self.headers = {"location": "https://attacker.example/v1"}
        self.body = body
        self.closed = False

    def read(self, *_args: object, **_kwargs: object) -> bytes:
        """Return configured response bytes."""
        return self.body

    def close(self) -> None:
        """Record response cleanup."""
        self.closed = True

    def __iter__(self):
        """Iterate one response line."""
        return iter([self.body])


class _FakeConnection:
    """Observable pinned TLS connection double."""

    created: list["_FakeConnection"] = []
    responses: dict[str, _FakeResponse] = {}
    failing_ips: set[str] = set()

    def __init__(
        self,
        hostname: str,
        pinned_ip: str,
        port: int,
        timeout: float,
        context: ssl.SSLContext,
    ) -> None:
        """Capture construction inputs for transport assertions."""
        self.hostname = hostname
        self.pinned_ip = pinned_ip
        self.port = port
        self.timeout = timeout
        self.context = context
        self.request_call: tuple[object, ...] | None = None
        self.closed = False
        self.created.append(self)

    def request(
        self,
        method: str,
        target: str,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        """Capture a request or simulate one address-level failure."""
        self.request_call = (method, target, body, headers)
        if self.pinned_ip in self.failing_ips:
            raise OSError("address unavailable")

    def getresponse(self) -> _FakeResponse:
        """Return the response configured for this address."""
        return self.responses[self.pinned_ip]

    def close(self) -> None:
        """Record connection cleanup."""
        self.closed = True


@pytest.fixture(autouse=True)
def _reset_credential_backend():
    """Restore the process-global credential backend after every test."""
    try:
        yield
    finally:
        set_backend(None)


def _configured_client() -> tuple[ModelClient, ModelAgent]:
    """Build a client and HTTPS agent with a resolvable KV credential."""
    backend = InMemoryCredentialBackend()
    backend.set("MODEL_KEY", "test-provider-secret")
    set_backend(backend)
    client = ModelClient(timeout=11)
    client._https_connection_class = _FakeConnection
    agent = ModelAgent(
        "provider_agent",
        "provider-model",
        "https://api.example.com:8443/v1",
        "MODEL_KEY",
    )
    _FakeConnection.created = []
    _FakeConnection.responses = {}
    _FakeConnection.failing_ips = set()
    return client, agent


def _public_dns_answers() -> list[tuple[int, int, int, str, tuple[str, int]]]:
    """Return duplicate and distinct globally routable IPv4 answers."""
    return [
        (2, 1, 6, "", ("93.184.216.34", 8443)),
        (2, 1, 6, "", ("93.184.216.34", 8443)),
        (2, 1, 6, "", ("93.184.216.35", 8443)),
    ]


def test_transport_installer_is_idempotent() -> None:
    """Repeated package initialization cannot wrap validation more than once."""
    validate_method = ModelClient._validate_provider
    open_method = ModelClient._open_provider
    install_provider_transport(ModelClient)
    assert ModelClient._validate_provider is validate_method
    assert ModelClient._open_provider is open_method


def test_validated_public_addresses_supports_ipv6_and_deduplicates() -> None:
    """Address validation returns unique normalized public IPv4 and IPv6 pins."""
    answers = [
        (2, 1, 6, "", ("93.184.216.34", 443)),
        (2, 1, 6, "", ("93.184.216.34", 443)),
        (10, 1, 6, "", ("2606:2800:220:1:248:1893:25c8:1946", 443, 0, 0)),
    ]
    with mock.patch(
        "contextual_orchestrator.provider_transport.socket.getaddrinfo",
        return_value=answers,
    ):
        assert _validated_public_addresses("api.example.com", 443, "provider_agent") == (
            "93.184.216.34",
            "2606:2800:220:1:248:1893:25c8:1946",
        )


@pytest.mark.parametrize("unsafe_address", ["127.0.0.1", "100.64.0.1", "224.0.0.1"])
def test_validated_public_addresses_rejects_unsafe_answer(unsafe_address: str) -> None:
    """Any unsafe member of a DNS answer causes validation to fail closed."""
    answers = [
        (2, 1, 6, "", ("93.184.216.34", 443)),
        (2, 1, 6, "", (unsafe_address, 443)),
    ]
    with mock.patch(
        "contextual_orchestrator.provider_transport.socket.getaddrinfo",
        return_value=answers,
    ):
        with pytest.raises(RuntimeError, match="non-public address"):
            _validated_public_addresses("api.example.com", 443, "provider_agent")


def test_validated_public_addresses_rejects_empty_answer() -> None:
    """An empty resolver answer cannot silently create an unpinned request."""
    with mock.patch(
        "contextual_orchestrator.provider_transport.socket.getaddrinfo",
        return_value=[],
    ):
        with pytest.raises(RuntimeError, match="did not resolve"):
            _validated_public_addresses("api.example.com", 443, "provider_agent")


def test_validate_then_open_uses_same_dns_answer_without_reresolution() -> None:
    """The connected addresses come only from the validation-time DNS answer."""
    client, agent = _configured_client()
    with mock.patch(
        "contextual_orchestrator.orchestrator.socket.getaddrinfo",
        return_value=_public_dns_answers(),
    ) as policy_resolver, mock.patch(
        "contextual_orchestrator.provider_transport.socket.getaddrinfo",
        return_value=_public_dns_answers(),
    ) as pin_resolver:
        client._validate_provider(agent)
    assert policy_resolver.call_count == 1
    assert pin_resolver.call_count == 1

    _FakeConnection.failing_ips = {"93.184.216.34"}
    _FakeConnection.responses = {"93.184.216.35": _FakeResponse(body=b"success")}
    request = urllib.request.Request(
        "https://api.example.com:8443/v1/chat;mode=fast?trace=yes",
        data=b"{}",
        headers={"authorization": "Bearer secret"},
        method="POST",
    )
    with mock.patch(
        "contextual_orchestrator.orchestrator.socket.getaddrinfo",
        side_effect=AssertionError("transport must not resolve policy DNS again"),
    ), mock.patch(
        "contextual_orchestrator.provider_transport.socket.getaddrinfo",
        side_effect=AssertionError("transport must not resolve pin DNS again"),
    ):
        with client._open_provider(request) as response:
            assert response.read() == b"success"

    first, second = _FakeConnection.created
    assert first.closed is True
    assert second.hostname == "api.example.com"
    assert second.port == 8443
    assert second.timeout == 11
    assert second.request_call == (
        "POST",
        "/v1/chat;mode=fast?trace=yes",
        b"{}",
        {"Authorization": "Bearer secret", "Connection": "close"},
    )
    assert second.closed is True


def test_failed_revalidation_clears_existing_pin() -> None:
    """A later unsafe DNS answer cannot reuse a formerly valid cached address."""
    client, agent = _configured_client()
    with mock.patch(
        "contextual_orchestrator.orchestrator.socket.getaddrinfo",
        return_value=_public_dns_answers(),
    ), mock.patch(
        "contextual_orchestrator.provider_transport.socket.getaddrinfo",
        return_value=_public_dns_answers(),
    ):
        client._validate_provider(agent)

    unsafe = [(2, 1, 6, "", ("127.0.0.1", 8443))]
    with mock.patch(
        "contextual_orchestrator.orchestrator.socket.getaddrinfo",
        return_value=unsafe,
    ):
        with pytest.raises(RuntimeError, match="non-public address"):
            client._validate_provider(agent)

    request = urllib.request.Request("https://api.example.com:8443/v1/chat")
    with pytest.raises(RuntimeError, match="no validated address pin"):
        client._open_provider(request)


def test_redirect_response_is_rejected_without_following_location() -> None:
    """A redirect cannot forward provider credentials to another destination."""
    client, agent = _configured_client()
    answers = [(2, 1, 6, "", ("93.184.216.34", 8443))]
    with mock.patch(
        "contextual_orchestrator.orchestrator.socket.getaddrinfo",
        return_value=answers,
    ), mock.patch(
        "contextual_orchestrator.provider_transport.socket.getaddrinfo",
        return_value=answers,
    ):
        client._validate_provider(agent)

    response = _FakeResponse(status=302)
    _FakeConnection.responses = {"93.184.216.34": response}
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        client._open_provider(
            urllib.request.Request("https://api.example.com:8443/v1/chat", method="POST")
        )
    assert exc_info.value.code == 302
    assert response.closed is True
    assert _FakeConnection.created[0].closed is True
    assert len(_FakeConnection.created) == 1


def test_all_pinned_addresses_failing_returns_network_error() -> None:
    """Exhausting all approved addresses yields one urllib-compatible error."""
    client, agent = _configured_client()
    with mock.patch(
        "contextual_orchestrator.orchestrator.socket.getaddrinfo",
        return_value=_public_dns_answers(),
    ), mock.patch(
        "contextual_orchestrator.provider_transport.socket.getaddrinfo",
        return_value=_public_dns_answers(),
    ):
        client._validate_provider(agent)

    _FakeConnection.failing_ips = {"93.184.216.34", "93.184.216.35"}
    with pytest.raises(urllib.error.URLError, match="address unavailable"):
        client._open_provider(urllib.request.Request("https://api.example.com:8443", method="GET"))
    assert all(connection.closed for connection in _FakeConnection.created)


def test_open_provider_rejects_unsupported_scheme() -> None:
    """The low-level transport independently rejects non-HTTP provider schemes."""
    client = ModelClient()
    with pytest.raises(RuntimeError, match=r"http\(s\)"):
        client._open_provider(urllib.request.Request("file:///etc/passwd"))


def test_provider_response_delegates_metadata_iteration_read_and_cleanup() -> None:
    """The wrapper preserves response behavior and always closes its connection."""
    response = mock.Mock()
    response.status = 200
    response.read.return_value = b"payload"
    response.__iter__ = mock.Mock(return_value=iter([b"one", b"two"]))
    connection = mock.Mock()
    wrapper = _ProviderHTTPResponse(response, connection)
    with wrapper as entered:
        assert entered is wrapper
        assert wrapper.status == 200
        assert wrapper.read(4) == b"payload"
        assert list(wrapper) == [b"one", b"two"]
    response.read.assert_called_once_with(4)
    response.close.assert_called_once_with()
    connection.close.assert_called_once_with()


def test_provider_response_closes_connection_when_response_close_fails() -> None:
    """Connection cleanup survives an exception from response cleanup."""
    response = mock.Mock()
    response.close.side_effect = RuntimeError("close failed")
    connection = mock.Mock()
    wrapper = _ProviderHTTPResponse(response, connection)
    with pytest.raises(RuntimeError, match="close failed"):
        wrapper.close()
    connection.close.assert_called_once_with()


def test_pinned_https_connection_dials_ip_and_preserves_sni() -> None:
    """The direct socket uses the pin while TLS verifies the original hostname."""
    raw_socket = mock.Mock()
    wrapped_socket = object()
    context = mock.Mock()
    context.wrap_socket.return_value = wrapped_socket
    with mock.patch(
        "contextual_orchestrator.provider_transport.socket.create_connection",
        return_value=raw_socket,
    ) as create_connection:
        connection = _PinnedHTTPSConnection(
            "api.example.com",
            "93.184.216.34",
            443,
            7.0,
            context,
        )
        connection.connect()
    create_connection.assert_called_once_with(("93.184.216.34", 443), 7.0, None)
    context.wrap_socket.assert_called_once_with(raw_socket, server_hostname="api.example.com")
    assert connection.sock is wrapped_socket


def test_pinned_https_connection_closes_socket_when_tls_setup_fails() -> None:
    """A TLS setup failure cannot leak the already-connected raw socket."""
    raw_socket = mock.Mock()
    context = mock.Mock()
    context.wrap_socket.side_effect = ssl.SSLError("handshake failed")
    with mock.patch(
        "contextual_orchestrator.provider_transport.socket.create_connection",
        return_value=raw_socket,
    ):
        connection = _PinnedHTTPSConnection(
            "api.example.com",
            "93.184.216.34",
            443,
            7.0,
            context,
        )
        with pytest.raises(ssl.SSLError, match="handshake failed"):
            connection.connect()
    raw_socket.close.assert_called_once_with()
