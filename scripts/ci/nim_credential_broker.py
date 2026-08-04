#!/usr/bin/env python3
"""Run a credential-isolated, fixed-upstream NVIDIA NIM HTTP broker.

The hourly product-development workflow executes OpenCode in a container that
has no NVIDIA credential and no direct Internet route. This module runs in a
separate container, accepts only the two OpenAI-compatible operations required
by the agent, injects the API key into a TLS-verified request to NVIDIA's fixed
host, and returns a bounded response without sensitive headers or logs.
"""

from __future__ import annotations

import http.client
import json
import os
import ssl
import threading
import urllib.parse
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Final


UPSTREAM_HOST: Final = "integrate.api.nvidia.com"
UPSTREAM_PORT: Final = 443
ALLOWED_PATHS: Final = frozenset(
    {
        ("GET", "/v1/models"),
        ("POST", "/v1/chat/completions"),
    }
)
MAX_REQUESTS: Final = 128
MAX_REQUEST_BYTES: Final = 2 * 1024 * 1024
MAX_RESPONSE_BYTES: Final = 32 * 1024 * 1024
MAX_CONCURRENT_REQUESTS: Final = 2
UPSTREAM_TIMEOUT_SECONDS: Final = 300.0

ConnectionFactory = Callable[..., http.client.HTTPSConnection]


@dataclass(frozen=True, slots=True)
class BrokerResponse:
    """Represent one sanitized response returned to the isolated agent.

    Attributes:
        status: HTTP status code returned by the broker.
        body: Bounded response bytes that contain no broker credential.
        content_type: Media type sent to the agent.
    """

    status: int
    body: bytes
    content_type: str = "application/json"


class Reservation(Enum):
    """Describe whether a request acquired the broker's bounded capacity."""

    ACCEPTED = "accepted"
    REQUEST_LIMIT = "request_limit"
    CONCURRENCY_LIMIT = "concurrency_limit"


class RequestGovernor:
    """Enforce total-call and simultaneous-call limits across broker threads."""

    def __init__(self, max_requests: int, max_concurrent_requests: int) -> None:
        """Create a governor with positive request and concurrency limits.

        Args:
            max_requests: Maximum accepted requests during the broker process.
            max_concurrent_requests: Maximum upstream requests in flight.

        Raises:
            ValueError: If either limit is not positive.
        """

        if max_requests < 1 or max_concurrent_requests < 1:
            raise ValueError("request and concurrency limits must be positive")
        self._max_requests = max_requests
        self._request_count = 0
        self._request_lock = threading.Lock()
        self._concurrency = threading.BoundedSemaphore(max_concurrent_requests)

    def reserve(self) -> Reservation:
        """Reserve one total request and one concurrent execution slot.

        Returns:
            A reservation result that distinguishes exhausted total and active
            request budgets. A concurrency rejection still consumes one total
            request so callers cannot spin indefinitely against a busy broker.
        """

        with self._request_lock:
            if self._request_count >= self._max_requests:
                return Reservation.REQUEST_LIMIT
            self._request_count += 1
        if not self._concurrency.acquire(blocking=False):
            return Reservation.CONCURRENCY_LIMIT
        return Reservation.ACCEPTED

    def release(self) -> None:
        """Release one previously accepted concurrent execution slot."""

        self._concurrency.release()


class NIMCredentialBroker:
    """Validate and relay bounded requests to NVIDIA's fixed NIM endpoint."""

    def __init__(
        self,
        api_key: str,
        *,
        governor: RequestGovernor | None = None,
        connection_factory: ConnectionFactory = http.client.HTTPSConnection,
    ) -> None:
        """Create a broker without exposing its key to request callers.

        Args:
            api_key: NVIDIA NIM API key injected only into upstream requests.
            governor: Optional request governor, primarily for deterministic
                testing. The production default applies the module budgets.
            connection_factory: HTTPS connection constructor used for the fixed
                upstream host. Tests may inject a network-free implementation.

        Raises:
            ValueError: If ``api_key`` is empty or whitespace-only.
        """

        if not api_key.strip():
            raise ValueError("NVIDIA NIM API key must be nonempty")
        self._api_key = api_key
        self.governor = governor or RequestGovernor(
            MAX_REQUESTS,
            MAX_CONCURRENT_REQUESTS,
        )
        self.connection_factory = connection_factory

    @staticmethod
    def _error(status: int, message: str) -> BrokerResponse:
        """Build a deterministic JSON error without upstream exception detail."""

        payload = json.dumps(
            {"error": {"message": message}},
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return BrokerResponse(status, payload)

    @staticmethod
    def _validate_target(method: str, target: str) -> BrokerResponse | str:
        """Return an allowlisted path or a sanitized validation response."""

        parsed = urllib.parse.urlsplit(target)
        if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
            return NIMCredentialBroker._error(400, "unsupported broker target")
        if (method, parsed.path) not in ALLOWED_PATHS:
            return NIMCredentialBroker._error(404, "unsupported broker operation")
        return parsed.path

    @staticmethod
    def _validate_body(
        method: str,
        headers: Mapping[str, str],
        body: bytes,
    ) -> BrokerResponse | bytes | None:
        """Validate and canonicalize a chat body, or return no body for GET."""

        if method == "GET":
            return None
        raw_length = headers.get("Content-Length", "")
        if not raw_length.isdigit():
            return NIMCredentialBroker._error(411, "content length is required")
        content_length = int(raw_length)
        if content_length < 1 or content_length > MAX_REQUEST_BYTES:
            return NIMCredentialBroker._error(413, "request exceeds broker budget")
        if content_length != len(body):
            return NIMCredentialBroker._error(400, "request body length mismatch")
        try:
            document = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return NIMCredentialBroker._error(400, "request must be valid JSON")
        if not isinstance(document, dict):
            return NIMCredentialBroker._error(400, "request JSON must be an object")
        return json.dumps(
            document,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")

    def handle(
        self,
        method: str,
        target: str,
        headers: Mapping[str, str],
        body: bytes,
    ) -> BrokerResponse:
        """Handle one agent request under every broker trust boundary.

        Args:
            method: HTTP method supplied by the local agent.
            target: Origin-form request target supplied by the local agent.
            headers: Caller headers; only Content-Length is inspected and no
                caller credential, cookie, host, or forwarding header is used.
            body: Request bytes read under the declared Content-Length bound.

        Returns:
            A bounded, sanitized response suitable for the isolated agent.
        """

        if method == "GET" and target == "/healthz":
            return BrokerResponse(200, b'{"status":"ready"}')

        validated_target = self._validate_target(method, target)
        if isinstance(validated_target, BrokerResponse):
            return validated_target
        validated_body = self._validate_body(method, headers, body)
        if isinstance(validated_body, BrokerResponse):
            return validated_body

        reservation = self.governor.reserve()
        if reservation is Reservation.REQUEST_LIMIT:
            return self._error(429, "broker request budget exhausted")
        if reservation is Reservation.CONCURRENCY_LIMIT:
            return self._error(429, "broker concurrency budget exhausted")

        connection: http.client.HTTPSConnection | None = None
        try:
            connection = self.connection_factory(
                UPSTREAM_HOST,
                UPSTREAM_PORT,
                timeout=UPSTREAM_TIMEOUT_SECONDS,
                context=ssl.create_default_context(),
            )
            upstream_headers = {
                "Accept": "application/json, text/event-stream",
                "Accept-Encoding": "identity",
                "Authorization": f"Bearer {self._api_key}",
                "Connection": "close",
                "Host": UPSTREAM_HOST,
                "User-Agent": "contextual-orchestrator-nim-broker/1",
            }
            if validated_body is not None:
                upstream_headers["Content-Type"] = "application/json"
            connection.request(
                method,
                validated_target,
                body=validated_body,
                headers=upstream_headers,
            )
            response = connection.getresponse()
            if 300 <= response.status < 400:
                response.read(MAX_RESPONSE_BYTES + 1)
                return self._error(502, "upstream redirects are not allowed")
            response_body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(response_body) > MAX_RESPONSE_BYTES:
                return self._error(502, "upstream response exceeds broker budget")
            content_type = response.getheader("Content-Type", "application/json")
            content_type = content_type or "application/json"
            normalized_type = content_type.split(";", 1)[0].strip().lower()
            if normalized_type not in {"application/json", "text/event-stream"}:
                return self._error(502, "unsupported upstream content type")
            return BrokerResponse(response.status, response_body, content_type)
        except (OSError, http.client.HTTPException, ssl.SSLError, TimeoutError):
            return self._error(502, "NVIDIA NIM request failed")
        finally:
            if connection is not None:
                connection.close()
            self.governor.release()


def build_handler(
    application: NIMCredentialBroker,
) -> type[BaseHTTPRequestHandler]:
    """Create an HTTP handler class bound to one broker application."""

    class BrokerHandler(BaseHTTPRequestHandler):
        """Adapt stdlib HTTP requests to the credential broker application."""

        protocol_version = "HTTP/1.1"
        server_version = "ContextualOrchestratorNIMBroker"
        sys_version = ""

        def log_message(self, _format: str, *_args: object) -> None:
            """Suppress logs so prompts and request metadata never reach CI logs."""

        def _write_response(self, response: BrokerResponse) -> None:
            """Write one sanitized response with explicit length and no caching."""

            self.send_response(response.status)
            self.send_header("Content-Type", response.content_type)
            self.send_header("Content-Length", str(len(response.body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            if response.body:
                self.wfile.write(response.body)
            self.close_connection = True

        def do_GET(self) -> None:
            """Serve health or the allowlisted NIM model catalog operation."""

            self._write_response(application.handle("GET", self.path, self.headers, b""))

        def do_POST(self) -> None:
            """Read a bounded body and serve the allowlisted chat operation."""

            raw_length = self.headers.get("Content-Length", "")
            body = b""
            if raw_length.isdigit():
                content_length = int(raw_length)
                if 0 <= content_length <= MAX_REQUEST_BYTES:
                    body = self.rfile.read(content_length)
            self._write_response(
                application.handle("POST", self.path, self.headers, body)
            )

    return BrokerHandler


def create_server(
    application: NIMCredentialBroker,
    *,
    host: str = "0.0.0.0",
    port: int = 8001,
) -> ThreadingHTTPServer:
    """Create a daemon-thread HTTP server for one broker application.

    Args:
        application: Credential broker that handles validated requests.
        host: Interface address on the broker's private Docker network.
        port: Unprivileged TCP port exposed only inside that network.

    Returns:
        A configured server that the caller may run or stop explicitly.
    """

    server = ThreadingHTTPServer((host, port), build_handler(application))
    server.daemon_threads = True
    return server


def main() -> int:
    """Read the NIM secret, start the private broker, and serve until stopped.

    Returns:
        Zero after an orderly server shutdown.

    Raises:
        SystemExit: If ``NVIDIA_API_KEY`` is absent or empty.
    """

    api_key = os.environ.get("NVIDIA_API_KEY", "")
    if not api_key.strip():
        raise SystemExit("NVIDIA_API_KEY is required by the credential broker")
    server = create_server(NIMCredentialBroker(api_key))
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":  # pragma: no cover - executable boundary
    raise SystemExit(main())
