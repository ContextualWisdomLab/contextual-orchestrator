"""Passthrough transport response bounds (issue #1041).

``_send_raw`` is the primary full-JSON passthrough transport. On current
``main`` it does a bare ``response.read()``, so an oversized or hostile
provider body is buffered without limit (CWE-400). The bounded-read helper
already exists for sibling transports; this pins it to the passthrough path
and checks the typed failure is not collapsed by the retry classifier.
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import socket
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent  # noqa: E402
from contextual_orchestrator.orchestrator import (  # noqa: E402
    MAX_PROVIDER_RESPONSE_BYTES,
    ModelClient,
    ProviderResponseError,
)


def _oversized_body() -> bytes:
    content = "x" * (MAX_PROVIDER_RESPONSE_BYTES + 1)
    body = {"choices": [{"message": {"role": "assistant", "content": content}}]}
    return json.dumps(body).encode("utf-8")


class _BoundedProvider:
    """Serve one scripted raw body, optionally declaring content-length."""

    def __init__(self, raw: bytes, *, declare_length: bool) -> None:
        outer = self
        self.raw = raw
        self.declare_length = declare_length
        self.request_count = 0

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("content-length", 0))
                self.rfile.read(length)
                outer.request_count += 1
                self.send_response(200)
                self.send_header("content-type", "application/json")
                if outer.declare_length:
                    self.send_header("content-length", str(len(outer.raw)))
                self.end_headers()
                try:
                    self.wfile.write(outer.raw)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def log_message(self, *args: object) -> None:  # silence
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def __enter__(self) -> "_BoundedProvider":
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._server.shutdown()

    @property
    def destination(self) -> tuple[int, tuple[object, ...]]:
        return (socket.AF_INET, ("127.0.0.1", self._server.server_address[1]))

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}"


def _agent(base_url: str) -> ModelAgent:
    return ModelAgent("worker_agent", "gpt-x", base_url=base_url, api_key_env="UNSET_KEY_ENV")


def _passthrough_target(provider: _BoundedProvider):
    client = ModelClient(max_retries=0, retry_backoff=0.0)
    return client, provider.destination


def test_send_raw_rejects_declared_oversized_response() -> None:
    """A declared content-length above the cap fails closed before buffering."""
    with _BoundedProvider(_oversized_body(), declare_length=True) as provider:
        client, destination = _passthrough_target(provider)
        try:
            client._send_raw(
                _agent(provider.base_url),
                "chat/completions",
                {"model": "gpt-x"},
                destination,
            )
        except ProviderResponseError as exc:
            assert str(exc) == "provider response exceeds the configured limit"
        else:  # pragma: no cover - RED before the fix
            raise AssertionError("oversized passthrough response was accepted")


def test_send_raw_rejects_undeclared_oversized_response() -> None:
    """A body with no content-length is cut off at the cap, not fully buffered."""
    with _BoundedProvider(_oversized_body(), declare_length=False) as provider:
        client, destination = _passthrough_target(provider)
        try:
            client._send_raw(
                _agent(provider.base_url),
                "chat/completions",
                {"model": "gpt-x"},
                destination,
            )
        except ProviderResponseError as exc:
            assert str(exc) == "provider response exceeds the configured limit"
        else:  # pragma: no cover - RED before the fix
            raise AssertionError("oversized passthrough response was accepted")


def test_send_raw_with_retry_preserves_response_bound_error() -> None:
    """The typed bound failure is never collapsed into a retryable api_error."""

    class _BoundedClient(ModelClient):
        attempts = 0

        def _send_raw(self, agent, endpoint, payload, destination=None):  # type: ignore[override]
            _BoundedClient.attempts += 1
            raise ProviderResponseError(
                "provider response exceeds the configured limit"
            )

    client = _BoundedClient(max_retries=3, retry_backoff=0.0)
    try:
        client._send_raw_with_retry(
            _agent("http://127.0.0.1:1"), "chat/completions", {"model": "gpt-x"}
        )
    except ProviderResponseError as exc:
        assert str(exc) == "provider response exceeds the configured limit"
    else:  # pragma: no cover - RED before the fix
        raise AssertionError("response bound failure did not propagate")
    assert _BoundedClient.attempts == 1  # a size violation is not retried


def test_send_raw_accepts_normal_response_over_http() -> None:
    """A within-limit passthrough response still round-trips unchanged."""
    body = json.dumps(
        {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}
    ).encode("utf-8")
    with _BoundedProvider(body, declare_length=True) as provider:
        client, destination = _passthrough_target(provider)
        result = client._send_raw(
            _agent(provider.base_url),
            "chat/completions",
            {"model": "gpt-x"},
            destination,
        )
    assert result["choices"][0]["message"]["content"] == "ok"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
    print("ok")
