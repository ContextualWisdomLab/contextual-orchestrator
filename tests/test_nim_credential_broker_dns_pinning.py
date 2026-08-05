"""DNS-pinning contracts for the scheduled NVIDIA NIM credential broker."""

from __future__ import annotations

import socket
from typing import Any

import pytest

from scripts.ci import nim_credential_broker as broker


class _FakeResponse:
    """Return one bounded JSON response or one configured transport failure."""

    def __init__(self, *, error: BaseException | None = None) -> None:
        """Store the optional failure raised when the broker reads the response."""

        self.status = 200
        self.error = error

    def read(self, amount: int) -> bytes:
        """Return a bounded response body after honoring a configured failure."""

        assert amount == broker.MAX_RESPONSE_BYTES + 1
        if self.error is not None:
            raise self.error
        return b'{"ok":true}'

    def getheader(self, name: str, default: str | None = None) -> str | None:
        """Return a safe JSON media type for the broker response contract."""

        assert name == "Content-Type"
        return "application/json" if default is not None else "application/json"


class _FakePinnedConnection:
    """Record one approved-address request without opening a network socket."""

    instances: list["_FakePinnedConnection"] = []
    fail_first = False

    def __init__(
        self,
        server_hostname: str,
        pinned_ip: str,
        port: int,
        timeout: float,
        context: Any,
    ) -> None:
        """Record the original hostname, pinned IP, and TLS constructor inputs."""

        self.server_hostname = server_hostname
        self.pinned_ip = pinned_ip
        self.port = port
        self.timeout = timeout
        self.context = context
        self.requests: list[tuple[str, str, bytes | None, dict[str, str]]] = []
        self.closed = False
        self.index = len(self.instances)
        self.instances.append(self)

    def request(
        self,
        method: str,
        path: str,
        body: bytes | None,
        headers: dict[str, str],
    ) -> None:
        """Record the exact request relayed to one validated address."""

        self.requests.append((method, path, body, headers))

    def getresponse(self) -> _FakeResponse:
        """Fail the first address when requested, otherwise return JSON."""

        if self.fail_first and self.index == 0:
            raise OSError("first approved address unavailable")
        return _FakeResponse()

    def close(self) -> None:
        """Record deterministic cleanup for every attempted address."""

        self.closed = True


def _address_record(address: str) -> tuple[Any, ...]:
    """Build one ``getaddrinfo``-compatible stream-address record."""

    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    sockaddr: tuple[Any, ...]
    if family == socket.AF_INET6:
        sockaddr = (address, broker.UPSTREAM_PORT, 0, 0)
    else:
        sockaddr = (address, broker.UPSTREAM_PORT)
    return (family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", sockaddr)


def test_validated_public_addresses_deduplicate_global_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only deterministic globally routable DNS answers become dial candidates."""

    monkeypatch.setattr(
        broker.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            _address_record("93.184.216.34"),
            _address_record("2606:2800:220:1:248:1893:25c8:1946"),
            _address_record("93.184.216.34"),
        ],
    )

    assert broker._validated_public_addresses(  # noqa: SLF001 - security contract.
        broker.UPSTREAM_HOST,
        broker.UPSTREAM_PORT,
    ) == (
        "93.184.216.34",
        "2606:2800:220:1:248:1893:25c8:1946",
    )


@pytest.mark.parametrize(
    "records",
    [
        [],
        [_address_record("127.0.0.1")],
        [
            _address_record("93.184.216.34"),
            _address_record("10.0.0.7"),
        ],
        [
            _address_record(f"192.0.2.{index}")
            for index in range(1, broker.MAX_UPSTREAM_ADDRESSES + 2)
        ],
    ],
)
def test_validated_public_addresses_fail_closed_on_unsafe_catalogs(
    monkeypatch: pytest.MonkeyPatch,
    records: list[tuple[Any, ...]],
) -> None:
    """Empty, non-global, mixed, and excessive DNS answers never reach TLS."""

    monkeypatch.setattr(
        broker.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: records,
    )

    with pytest.raises(OSError, match="NVIDIA NIM upstream"):
        broker._validated_public_addresses(  # noqa: SLF001 - security contract.
            broker.UPSTREAM_HOST,
            broker.UPSTREAM_PORT,
        )


def test_default_broker_transport_retries_only_pinned_global_addresses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The secret-bearing request dials only the once-validated address set."""

    _FakePinnedConnection.instances = []
    _FakePinnedConnection.fail_first = True
    monkeypatch.setattr(
        broker,
        "_validated_public_addresses",
        lambda *_args: ("93.184.216.34", "2606:2800:220:1:248:1893:25c8:1946"),
    )
    monkeypatch.setattr(broker, "_PinnedHTTPSConnection", _FakePinnedConnection)

    application = broker.NIMCredentialBroker("top-secret")
    response = application.handle("GET", "/v1/models", {}, b"")

    assert response.status == 200
    assert [connection.pinned_ip for connection in _FakePinnedConnection.instances] == [
        "93.184.216.34",
        "2606:2800:220:1:248:1893:25c8:1946",
    ]
    assert all(
        connection.server_hostname == broker.UPSTREAM_HOST
        for connection in _FakePinnedConnection.instances
    )
    assert all(connection.closed for connection in _FakePinnedConnection.instances)
    for connection in _FakePinnedConnection.instances:
        assert connection.requests[0][3]["Authorization"] == "Bearer top-secret"
        assert connection.requests[0][3]["Host"] == broker.UPSTREAM_HOST


def test_default_broker_transport_rejects_non_global_dns_before_egress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A DNS-rebinding answer fails before any credential-bearing connection."""

    monkeypatch.setattr(
        broker,
        "_validated_public_addresses",
        lambda *_args: (_ for _ in ()).throw(
            OSError("NVIDIA NIM upstream resolved to non-global address")
        ),
    )

    def unexpected_connection(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("non-global DNS must fail before TLS construction")

    monkeypatch.setattr(broker, "_PinnedHTTPSConnection", unexpected_connection)
    application = broker.NIMCredentialBroker("top-secret")

    response = application.handle("GET", "/v1/models", {}, b"")

    assert response.status == 502
    assert b"non-global" not in response.body
    assert b"top-secret" not in response.body


def test_pinned_https_connection_dials_ip_with_original_tls_hostname(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The low-level socket uses the pin while TLS authenticates the host name."""

    class RawSocket:
        """Record whether failed TLS setup closes the unwrapped socket."""

        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    class TLSContext:
        """Record SNI and return a deterministic wrapped socket."""

        def __init__(self, *, fail: bool = False) -> None:
            self.fail = fail
            self.calls: list[tuple[RawSocket, str]] = []

        def wrap_socket(self, raw_socket: RawSocket, *, server_hostname: str) -> object:
            self.calls.append((raw_socket, server_hostname))
            if self.fail:
                raise OSError("TLS setup failed")
            return object()

    created: list[tuple[tuple[str, int], float, Any]] = []
    raw_socket = RawSocket()

    def fake_create_connection(
        address: tuple[str, int],
        timeout: float,
        source_address: Any,
    ) -> RawSocket:
        created.append((address, timeout, source_address))
        return raw_socket

    monkeypatch.setattr(broker.socket, "create_connection", fake_create_connection)
    context = TLSContext()
    connection = broker._PinnedHTTPSConnection(  # noqa: SLF001 - security contract.
        broker.UPSTREAM_HOST,
        "93.184.216.34",
        broker.UPSTREAM_PORT,
        broker.UPSTREAM_TIMEOUT_SECONDS,
        context,
    )

    connection.connect()

    assert created == [
        (
            ("93.184.216.34", broker.UPSTREAM_PORT),
            broker.UPSTREAM_TIMEOUT_SECONDS,
            None,
        )
    ]
    assert context.calls == [(raw_socket, broker.UPSTREAM_HOST)]
    assert connection.sock is not None
    assert raw_socket.closed is False

    failed_raw_socket = RawSocket()
    monkeypatch.setattr(
        broker.socket,
        "create_connection",
        lambda *_args, **_kwargs: failed_raw_socket,
    )
    failing_connection = broker._PinnedHTTPSConnection(  # noqa: SLF001.
        broker.UPSTREAM_HOST,
        "93.184.216.34",
        broker.UPSTREAM_PORT,
        broker.UPSTREAM_TIMEOUT_SECONDS,
        TLSContext(fail=True),
    )

    with pytest.raises(OSError, match="TLS setup failed"):
        failing_connection.connect()
    assert failed_raw_socket.closed is True
