"""Inbound JSON request framing must fail closed before the socket read.

Issue #119: ``_read_json`` used ``int(Content-Length)`` and only rejected
``body_size > max_body_bytes``. A buyer (or attacker) who sends
``Content-Length: -1`` on an invoice-lookup POST reaches ``rfile.read(-1)``,
which reads until EOF and can stall past the configured body limit.

Fielding, R. (Ed.), Nottingham, M. (Ed.), & Reschke, J. (Ed.). (2022).
*HTTP semantics* (RFC 9110). RFC Editor. https://doi.org/10.17487/RFC9110

Fielding, R. (Ed.), Nottingham, M. (Ed.), & Reschke, J. (Ed.). (2022).
*HTTP/1.1* (RFC 9112). RFC Editor. https://doi.org/10.17487/RFC9112
"""

from __future__ import annotations

import json
import socket
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.server import (  # noqa: E402
    RequestError,
    SecurityConfig,
    _parse_content_length,
    build_server,
)

_TEST_AUTH_TOKEN = "request_framing_http_honesty_token"  # noqa: S105
_INVOICE_BODY = (
    b'{"model":"mock-planner","messages":[{"role":"user","content":"summarize invoice 4419"}]}'
)


class _HeaderMap:
    """Minimal header view for unit-level Content-Length checks."""

    def __init__(
        self,
        values: dict[str, str],
        all_values: dict[str, list[str]] | None = None,
    ) -> None:
        self._values = {key.lower(): value for key, value in values.items()}
        self._all = {key.lower(): value for key, value in (all_values or {}).items()}

    def get(self, key: str, default: str | None = None) -> str | None:
        return self._values.get(key.lower(), default)

    def get_all(self, key: str) -> list[str] | None:
        if key.lower() in self._all:
            return self._all[key.lower()]
        value = self._values.get(key.lower())
        return [value] if value is not None else None


def _start_server(max_body_bytes: int = 64):
    orchestrator = TaskOrchestrator(
        [ModelAgent("general_agent", "mock-planner", tags=("reasoning", "writing"))]
    )
    server = build_server(
        orchestrator,
        port=0,
        security=SecurityConfig(
            auth_token=_TEST_AUTH_TOKEN,
            rate_limit_requests=10_000,
            max_body_bytes=max_body_bytes,
        ),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def _raw_post(port: int, extra_headers: list[str], body: bytes) -> tuple[int, bytes]:
    request = (
        f"POST /v1/chat/completions HTTP/1.1\r\n"
        f"Host: 127.0.0.1:{port}\r\n"
        f"Authorization: Bearer {_TEST_AUTH_TOKEN}\r\n"
        f"Connection: close\r\n"
        + "".join(header + "\r\n" for header in extra_headers)
        + "\r\n"
    ).encode("ascii") + body
    with socket.create_connection(("127.0.0.1", port), timeout=3) as sock:
        sock.settimeout(3)
        sock.sendall(request)
        chunks: list[bytes] = []
        while True:
            try:
                data = sock.recv(4096)
            except TimeoutError:
                break
            if not data:
                break
            chunks.append(data)
    raw = b"".join(chunks)
    if not raw:
        raise AssertionError("server returned no response; request framing likely stalled")
    status_line = raw.split(b"\r\n", 1)[0]
    code = int(status_line.split()[1])
    return code, raw


def test_parse_content_length_rejects_negative_and_signed_forms() -> None:
    """Signed or non-decimal Content-Length must never become read(-1)."""
    for raw in ("-1", "+10", "12abc", "1.5", ""):
        try:
            _parse_content_length(_HeaderMap({"Content-Length": raw}), 64)
        except RequestError as exc:
            assert exc.code in {"invalid_content_length", "length_required"}
            assert exc.status in {400, 411}
        else:
            raise AssertionError(f"accepted illegal Content-Length {raw!r}")


def test_parse_content_length_rejects_chunked_transfer_encoding() -> None:
    """JSON POSTs must not accept chunked framing (RFC 9112 §6.1)."""
    try:
        _parse_content_length(
            _HeaderMap(
                {
                    "Content-Length": "10",
                    "Transfer-Encoding": "chunked",
                }
            ),
            64,
        )
    except RequestError as exc:
        assert exc.status == 400
        assert exc.code == "unsupported_transfer_encoding"
    else:
        raise AssertionError("accepted chunked Transfer-Encoding")


def test_parse_content_length_rejects_duplicate_content_length() -> None:
    """Ambiguous duplicate Content-Length must fail closed (RFC 9112 §6.3.3)."""
    try:
        _parse_content_length(
            _HeaderMap(
                {"Content-Length": "10, 12"},
                all_values={"Content-Length": ["10", "12"]},
            ),
            64,
        )
    except RequestError as exc:
        assert exc.status == 400
        assert exc.code == "invalid_content_length"
    else:
        raise AssertionError("accepted duplicate Content-Length")


def test_parse_content_length_accepts_unsigned_decimal_within_budget() -> None:
    """A legal invoice body length must be returned unchanged."""
    assert _parse_content_length(_HeaderMap({"Content-Length": str(len(_INVOICE_BODY))}), 4096) == len(
        _INVOICE_BODY
    )


def test_http_negative_content_length_is_rejected() -> None:
    """Invoice POST with Content-Length: -1 must 400, not stall on read(-1)."""
    server, thread, port = _start_server()
    try:
        code, raw = _raw_post(
            port,
            ["Content-Type: application/json", "Content-Length: -1"],
            _INVOICE_BODY,
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)
    assert code == 400
    assert b"invalid_content_length" in raw


def test_http_non_decimal_content_length_is_rejected() -> None:
    server, thread, port = _start_server()
    try:
        code, raw = _raw_post(
            port,
            ["Content-Type: application/json", "Content-Length: 12abc"],
            b"{}",
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)
    assert code == 400
    assert b"invalid_content_length" in raw


def test_http_missing_content_length_is_rejected() -> None:
    server, thread, port = _start_server()
    try:
        code, raw = _raw_post(
            port,
            ["Content-Type: application/json"],
            _INVOICE_BODY,
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)
    assert code == 411
    assert b"length_required" in raw


def test_http_oversized_content_length_is_rejected() -> None:
    server, thread, port = _start_server(max_body_bytes=64)
    try:
        code, raw = _raw_post(
            port,
            ["Content-Type: application/json", "Content-Length: 65"],
            b"x" * 65,
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)
    assert code == 413
    assert b"request_too_large" in raw


def test_http_chunked_transfer_encoding_is_rejected() -> None:
    server, thread, port = _start_server(max_body_bytes=4096)
    try:
        code, raw = _raw_post(
            port,
            [
                "Content-Type: application/json",
                f"Content-Length: {len(_INVOICE_BODY)}",
                "Transfer-Encoding: chunked",
            ],
            _INVOICE_BODY,
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)
    assert code == 400
    assert b"unsupported_transfer_encoding" in raw


def test_http_valid_invoice_json_still_completes() -> None:
    """A correctly framed invoice lookup must still return a chat completion."""
    server, thread, port = _start_server(max_body_bytes=4096)
    try:
        code, raw = _raw_post(
            port,
            [
                "Content-Type: application/json",
                f"Content-Length: {len(_INVOICE_BODY)}",
            ],
            _INVOICE_BODY,
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)
    assert code == 200
    payload = json.loads(raw.split(b"\r\n\r\n", 1)[1].decode("utf-8"))
    assert payload.get("object") == "chat.completion" or payload.get("choices")


if __name__ == "__main__":
    test_parse_content_length_rejects_negative_and_signed_forms()
    test_parse_content_length_rejects_chunked_transfer_encoding()
    test_parse_content_length_rejects_duplicate_content_length()
    test_parse_content_length_accepts_unsigned_decimal_within_budget()
    test_http_negative_content_length_is_rejected()
    test_http_non_decimal_content_length_is_rejected()
    test_http_missing_content_length_is_rejected()
    test_http_oversized_content_length_is_rejected()
    test_http_chunked_transfer_encoding_is_rejected()
    test_http_valid_invoice_json_still_completes()
    print("ok")
