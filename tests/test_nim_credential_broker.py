"""Behavior tests for the credential-isolated NVIDIA NIM broker."""

from __future__ import annotations

import http.client
import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest

from scripts.ci import nim_credential_broker as broker


class FakeResponse:
    """Minimal upstream response double used by broker unit tests."""

    def __init__(
        self,
        status: int = 200,
        body: bytes = b'{"ok":true}',
        content_type: str | None = "application/json",
    ) -> None:
        """Store the status, body, and content type returned by the fake upstream."""

        self.status = status
        self.body = body
        self.content_type = content_type
        self.read_limit: int | None = None

    def read(self, amount: int) -> bytes:
        """Return at most ``amount`` bytes and record the broker's read bound."""

        self.read_limit = amount
        return self.body[:amount]

    def getheader(self, name: str, default: str | None = None) -> str | None:
        """Return only the fake Content-Type header."""

        if name.lower() == "content-type":
            return self.content_type
        return default


class FakeConnection:
    """Record one broker-to-upstream request without using the network."""

    def __init__(
        self,
        response: FakeResponse | None = None,
        error: BaseException | None = None,
    ) -> None:
        """Configure the response or exception produced by ``getresponse``."""

        self.response = response or FakeResponse()
        self.error = error
        self.requests: list[tuple[str, str, bytes | None, dict[str, str]]] = []
        self.closed = False

    def request(
        self,
        method: str,
        path: str,
        body: bytes | None,
        headers: dict[str, str],
    ) -> None:
        """Record the exact request relayed by the broker."""

        self.requests.append((method, path, body, headers))

    def getresponse(self) -> FakeResponse:
        """Return the configured response or raise the configured transport error."""

        if self.error is not None:
            raise self.error
        return self.response

    def close(self) -> None:
        """Record deterministic connection cleanup."""

        self.closed = True


class FakeConnectionFactory:
    """Create one preconfigured connection and capture constructor arguments."""

    def __init__(self, connection: FakeConnection) -> None:
        """Store the connection returned for the next broker request."""

        self.connection = connection
        self.calls: list[tuple[str, int, float, Any]] = []

    def __call__(
        self,
        host: str,
        port: int,
        *,
        timeout: float,
        context: Any,
    ) -> FakeConnection:
        """Record fixed-upstream TLS constructor inputs and return the fake."""

        self.calls.append((host, port, timeout, context))
        return self.connection


@contextmanager
def running_server(
    application: broker.NIMCredentialBroker,
) -> Iterator[tuple[str, int]]:
    """Run a local broker HTTP server for handler-level integration tests."""

    server = broker.create_server(application, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield str(host), int(port)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_broker_requires_a_nonempty_api_key() -> None:
    """The credential boundary cannot start without its sole secret."""

    with pytest.raises(ValueError, match="API key"):
        broker.NIMCredentialBroker("")


@pytest.mark.parametrize("limits", [(0, 1), (1, 0), (-1, 1), (1, -1)])
def test_governor_rejects_nonpositive_limits(limits: tuple[int, int]) -> None:
    """A governor cannot silently disable either security budget."""

    with pytest.raises(ValueError, match="positive"):
        broker.RequestGovernor(*limits)


def test_health_and_target_validation_do_not_contact_upstream() -> None:
    """Health succeeds while absolute, queried, and unsupported targets fail closed."""

    connection = FakeConnection()
    factory = FakeConnectionFactory(connection)
    application = broker.NIMCredentialBroker("secret", connection_factory=factory)

    health = application.handle("GET", "/healthz", {}, b"")
    absolute = application.handle("GET", "https://example.test/v1/models", {}, b"")
    queried = application.handle("GET", "/v1/models?owner=all", {}, b"")
    unsupported = application.handle("GET", "/v1/unknown", {}, b"")

    assert health == broker.BrokerResponse(200, b'{"status":"ready"}')
    assert absolute.status == 400
    assert queried.status == 400
    assert unsupported.status == 404
    assert factory.calls == []


@pytest.mark.parametrize(
    ("headers", "body", "status"),
    [
        ({}, b"{}", 411),
        ({"Content-Length": "not-a-number"}, b"{}", 411),
        ({"Content-Length": "0"}, b"", 413),
        (
            {"Content-Length": str(broker.MAX_REQUEST_BYTES + 1)},
            b"",
            413,
        ),
        ({"Content-Length": "3"}, b"{}", 400),
        ({"Content-Length": "1"}, b"{", 400),
        ({"Content-Length": "2"}, b"[]", 400),
    ],
)
def test_post_body_validation_is_bounded_and_object_only(
    headers: dict[str, str],
    body: bytes,
    status: int,
) -> None:
    """Malformed, mismatched, oversized, and non-object bodies never reach NIM."""

    connection = FakeConnection()
    factory = FakeConnectionFactory(connection)
    application = broker.NIMCredentialBroker("secret", connection_factory=factory)

    response = application.handle(
        "POST",
        "/v1/chat/completions",
        headers,
        body,
    )

    assert response.status == status
    assert factory.calls == []


def test_chat_request_uses_fixed_tls_upstream_and_secret_header() -> None:
    """Caller headers are discarded and the real key appears only upstream."""

    upstream = FakeResponse(
        status=201,
        body=b'{"id":"completion"}',
        content_type="application/json; charset=utf-8",
    )
    connection = FakeConnection(upstream)
    factory = FakeConnectionFactory(connection)
    application = broker.NIMCredentialBroker("top-secret", connection_factory=factory)
    source = b'{"model":"demo","messages":[]}'

    response = application.handle(
        "POST",
        "/v1/chat/completions",
        {
            "Content-Length": str(len(source)),
            "Authorization": "Bearer attacker-controlled",
            "Cookie": "do-not-forward=true",
        },
        source,
    )

    assert response == broker.BrokerResponse(
        201,
        b'{"id":"completion"}',
        "application/json; charset=utf-8",
    )
    assert len(factory.calls) == 1
    host, port, timeout, tls_context = factory.calls[0]
    assert (host, port, timeout) == (
        broker.UPSTREAM_HOST,
        broker.UPSTREAM_PORT,
        broker.UPSTREAM_TIMEOUT_SECONDS,
    )
    assert tls_context.check_hostname is True
    assert len(connection.requests) == 1
    method, path, relayed_body, headers = connection.requests[0]
    assert (method, path) == ("POST", "/v1/chat/completions")
    assert json.loads(relayed_body or b"null") == json.loads(source)
    assert headers["Authorization"] == "Bearer top-secret"
    assert headers["Host"] == broker.UPSTREAM_HOST
    assert "Cookie" not in headers
    assert connection.closed is True
    assert upstream.read_limit == broker.MAX_RESPONSE_BYTES + 1


def test_model_catalog_request_has_no_body() -> None:
    """Catalog discovery uses the same fixed upstream without a request body."""

    connection = FakeConnection()
    application = broker.NIMCredentialBroker(
        "secret",
        connection_factory=FakeConnectionFactory(connection),
    )

    response = application.handle("GET", "/v1/models", {}, b"")

    assert response.status == 200
    assert connection.requests[0][0:3] == ("GET", "/v1/models", None)


def test_missing_upstream_content_type_defaults_to_json() -> None:
    """A missing upstream media type is normalized to the broker's safe default."""

    connection = FakeConnection(FakeResponse(content_type=None))
    application = broker.NIMCredentialBroker(
        "secret",
        connection_factory=FakeConnectionFactory(connection),
    )

    response = application.handle("GET", "/v1/models", {}, b"")

    assert response.status == 200
    assert response.content_type == "application/json"


@pytest.mark.parametrize(
    ("upstream", "expected_message"),
    [
        (FakeResponse(status=302), "redirects"),
        (
            FakeResponse(body=b"x" * (broker.MAX_RESPONSE_BYTES + 1)),
            "response exceeds",
        ),
        (FakeResponse(content_type="text/html"), "content type"),
    ],
)
def test_unsafe_upstream_responses_are_replaced_with_generic_errors(
    upstream: FakeResponse,
    expected_message: str,
) -> None:
    """Redirects, oversized bodies, and unexpected media types fail closed."""

    connection = FakeConnection(upstream)
    application = broker.NIMCredentialBroker(
        "secret",
        connection_factory=FakeConnectionFactory(connection),
    )

    response = application.handle("GET", "/v1/models", {}, b"")

    assert response.status == 502
    assert expected_message.encode() in response.body
    assert connection.closed is True


def test_transport_error_is_generic_and_releases_the_slot() -> None:
    """A failed upstream connection is closed and does not leak broker capacity."""

    governor = broker.RequestGovernor(max_requests=2, max_concurrent_requests=1)
    connection = FakeConnection(error=OSError("secret-bearing transport detail"))
    application = broker.NIMCredentialBroker(
        "secret",
        governor=governor,
        connection_factory=FakeConnectionFactory(connection),
    )

    failed = application.handle("GET", "/v1/models", {}, b"")
    replacement = FakeConnection()
    application.connection_factory = FakeConnectionFactory(replacement)
    succeeded = application.handle("GET", "/v1/models", {}, b"")

    assert failed.status == 502
    assert b"secret-bearing" not in failed.body
    assert succeeded.status == 200
    assert connection.closed is True


def test_connection_factory_error_is_generic_without_cleanup_failure() -> None:
    """A connection-construction error leaves no object to close and still releases capacity."""

    def fail_factory(*_args: Any, **_kwargs: Any) -> FakeConnection:
        raise OSError("private DNS failure detail")

    governor = broker.RequestGovernor(max_requests=2, max_concurrent_requests=1)
    application = broker.NIMCredentialBroker(
        "secret",
        governor=governor,
        connection_factory=fail_factory,
    )

    failed = application.handle("GET", "/v1/models", {}, b"")
    application.connection_factory = FakeConnectionFactory(FakeConnection())
    succeeded = application.handle("GET", "/v1/models", {}, b"")

    assert failed.status == 502
    assert b"private DNS" not in failed.body
    assert succeeded.status == 200


def test_request_and_concurrency_budgets_fail_closed() -> None:
    """The governor distinguishes exhausted call and active-request budgets."""

    request_governor = broker.RequestGovernor(
        max_requests=1,
        max_concurrent_requests=1,
    )
    application = broker.NIMCredentialBroker(
        "secret",
        governor=request_governor,
        connection_factory=FakeConnectionFactory(FakeConnection()),
    )
    assert application.handle("GET", "/v1/models", {}, b"").status == 200
    assert application.handle("GET", "/v1/models", {}, b"").status == 429

    concurrency_governor = broker.RequestGovernor(
        max_requests=2,
        max_concurrent_requests=1,
    )
    assert concurrency_governor.reserve() == broker.Reservation.ACCEPTED
    blocked_application = broker.NIMCredentialBroker(
        "secret",
        governor=concurrency_governor,
        connection_factory=FakeConnectionFactory(FakeConnection()),
    )
    blocked = blocked_application.handle("GET", "/v1/models", {}, b"")
    concurrency_governor.release()

    assert blocked.status == 429
    assert b"concurrency" in blocked.body


def test_http_handler_serves_health_and_chat_without_request_logging() -> None:
    """The stdlib HTTP adapter preserves broker responses for real clients."""

    connection = FakeConnection(
        FakeResponse(
            body=b'data: {"ok":true}\n\n',
            content_type="text/event-stream",
        )
    )
    application = broker.NIMCredentialBroker(
        "secret",
        connection_factory=FakeConnectionFactory(connection),
    )

    with running_server(application) as (host, port):
        client = http.client.HTTPConnection(host, port, timeout=5)
        client.request("GET", "/healthz")
        health = client.getresponse()
        assert health.status == 200
        assert health.read() == b'{"status":"ready"}'
        client.close()

        client = http.client.HTTPConnection(host, port, timeout=5)
        payload = b'{"model":"demo","messages":[]}'
        client.request(
            "POST",
            "/v1/chat/completions",
            body=payload,
            headers={"Content-Type": "application/json"},
        )
        chat = client.getresponse()
        assert chat.status == 200
        assert chat.getheader("Cache-Control") == "no-store"
        assert chat.read() == b'data: {"ok":true}\n\n'
        client.close()


def test_http_handler_rejects_bad_lengths_and_writes_empty_responses() -> None:
    """The HTTP adapter avoids unbounded reads and supports an empty bounded body."""

    empty_application = broker.NIMCredentialBroker(
        "secret",
        connection_factory=FakeConnectionFactory(FakeConnection(FakeResponse(body=b""))),
    )

    with running_server(empty_application) as (host, port):
        client = http.client.HTTPConnection(host, port, timeout=5)
        client.request("GET", "/v1/models")
        empty = client.getresponse()
        assert empty.status == 200
        assert empty.getheader("Content-Length") == "0"
        assert empty.read() == b""
        client.close()

        client = http.client.HTTPConnection(host, port, timeout=5)
        client.putrequest("POST", "/v1/chat/completions")
        client.putheader("Content-Length", "not-a-number")
        client.endheaders()
        malformed = client.getresponse()
        assert malformed.status == 411
        malformed.read()
        client.close()

        client = http.client.HTTPConnection(host, port, timeout=5)
        client.putrequest("POST", "/v1/chat/completions")
        client.putheader("Content-Length", str(broker.MAX_REQUEST_BYTES + 1))
        client.endheaders()
        oversized = client.getresponse()
        assert oversized.status == 413
        oversized.read()
        client.close()


def test_main_rejects_a_missing_environment_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """The executable entry point fails before binding when its secret is absent."""

    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)

    with pytest.raises(SystemExit, match="NVIDIA_API_KEY"):
        broker.main()


def test_main_serves_and_closes_with_a_configured_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The executable entry point owns deterministic server startup and cleanup."""

    class FakeServer:
        """Record the lifecycle managed by the broker entry point."""

        def __init__(self) -> None:
            self.served = False
            self.closed = False

        def serve_forever(self, *, poll_interval: float) -> None:
            assert poll_interval == 0.5
            self.served = True

        def server_close(self) -> None:
            self.closed = True

    fake_server = FakeServer()
    monkeypatch.setenv("NVIDIA_API_KEY", "configured-secret")
    monkeypatch.setattr(
        broker,
        "create_server",
        lambda _application: fake_server,
    )

    assert broker.main() == 0
    assert fake_server.served is True
    assert fake_server.closed is True
