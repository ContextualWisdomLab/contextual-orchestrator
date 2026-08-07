"""Regression coverage for the provider JSON trust boundary.

Provider-controlled structured responses are bounded before parsing, decoded as
strict UTF-8 JSON objects, and converted to stable errors that do not retain the
untrusted document in an exception cause.  These tests intentionally exercise
the boundary directly and prove every model-client JSON-object call site uses
it instead of decoding response bytes independently.
"""

from __future__ import annotations

from unittest import mock

import pytest

from contextual_orchestrator.orchestrator import ModelAgent, ModelClient
from contextual_orchestrator.provider_transport import _ProviderHTTPResponse


class _ByteResponse:
    """Small byte response with observable cleanup for decoder regressions."""

    def __init__(self, payload: bytes) -> None:
        """Store one provider-controlled body and initialize cleanup evidence."""
        self._payload = payload
        self.closed = False

    def read(self, amount: int | None = None) -> bytes:
        """Return at most the requested bytes, matching ``HTTPResponse.read``."""
        if amount is None or amount < 0:
            amount = len(self._payload)
        chunk = self._payload[:amount]
        self._payload = self._payload[amount:]
        return chunk

    def close(self) -> None:
        """Record deterministic response cleanup."""
        self.closed = True


class _JsonBoundaryResponse:
    """Context-managed sentinel proving callers use ``read_json_object``."""

    def __init__(self, value: dict[str, object]) -> None:
        """Retain the object returned by the reviewed JSON boundary."""
        self._value = value
        self.json_reads = 0
        self.closed = False

    def __enter__(self) -> "_JsonBoundaryResponse":
        """Return the sentinel as an opened provider response."""
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        """Record deterministic context-manager cleanup."""
        self.closed = True

    def read_json_object(self) -> dict[str, object]:
        """Return the already-validated provider JSON object."""
        self.json_reads += 1
        return self._value

    def read(self, _amount: int | None = None) -> bytes:
        """Fail if a caller bypasses the reviewed JSON-object boundary."""
        raise AssertionError("provider JSON call site bypassed read_json_object")


def _provider_agent() -> ModelAgent:
    """Return one two-word-ID HTTPS agent suitable for transport-unit seams."""
    return ModelAgent(
        id="provider_agent",
        model="provider-model",
        base_url="https://provider.example",
        credential_key="NVIDIA_NIM_API_KEY",
    )


@pytest.mark.parametrize(
    ("payload", "private_marker"),
    [
        (b'{"secret":"private-json-value",', "private-json-value"),
        (b'{"secret":"\xffprivate-utf8-value"}', "private-utf8-value"),
    ],
)
def test_malformed_provider_json_is_redacted_without_exception_cause(
    payload: bytes,
    private_marker: str,
) -> None:
    """Malformed syntax or UTF-8 cannot retain provider text in error evidence."""
    response = _ByteResponse(payload)
    connection = mock.Mock()
    wrapper = _ProviderHTTPResponse(response, connection, max_bytes=512)

    with pytest.raises(RuntimeError, match="provider JSON response is malformed") as error:
        with wrapper:
            wrapper.read_json_object()

    assert error.value.__cause__ is None
    assert private_marker not in str(error.value)
    assert private_marker not in repr(error.value)
    assert response.closed is True
    connection.close.assert_called_once_with()


@pytest.mark.parametrize("constant", [b"NaN", b"Infinity", b"-Infinity"])
def test_provider_json_rejects_non_finite_number_extensions(constant: bytes) -> None:
    """Python-specific non-finite extensions cannot cross the RFC 8259 boundary."""
    response = _ByteResponse(b'{"value":' + constant + b"}")
    wrapper = _ProviderHTTPResponse(response, mock.Mock(), max_bytes=512)

    with pytest.raises(RuntimeError, match="provider JSON response is malformed"):
        wrapper.read_json_object()


def test_provider_json_rejects_duplicate_object_member_names() -> None:
    """Duplicate member names fail closed instead of inheriting last-value wins."""
    response = _ByteResponse(b'{"choice":1,"choice":2}')
    wrapper = _ProviderHTTPResponse(response, mock.Mock(), max_bytes=512)

    with pytest.raises(RuntimeError, match="provider JSON response is malformed"):
        wrapper.read_json_object()


def test_provider_json_requires_top_level_object() -> None:
    """A syntactically valid scalar or array is not an OpenAI-compatible object."""
    response = _ByteResponse(b"[]")
    wrapper = _ProviderHTTPResponse(response, mock.Mock(), max_bytes=512)

    with pytest.raises(RuntimeError, match="provider JSON response must be an object"):
        wrapper.read_json_object()


def test_provider_json_accepts_valid_utf8_object() -> None:
    """Valid UTF-8 JSON objects preserve Unicode content after bounded parsing."""
    response = _ByteResponse('{"message":"안녕하세요","count":2}'.encode("utf-8"))
    wrapper = _ProviderHTTPResponse(response, mock.Mock(), max_bytes=512)

    assert wrapper.read_json_object() == {"message": "안녕하세요", "count": 2}


def test_model_client_json_object_paths_use_reviewed_boundary() -> None:
    """Chat, passthrough, upload, and batch metadata share one decoder boundary."""
    client = ModelClient()
    agent = _provider_agent()

    chat_response = _JsonBoundaryResponse(
        {"choices": [{"message": {"content": "ok"}}], "usage": {"total_tokens": 1}}
    )
    client._open_provider = mock.Mock(return_value=chat_response)  # type: ignore[method-assign]
    assert client._send(agent, {"model": agent.model}) == "ok"
    assert chat_response.json_reads == 1
    assert chat_response.closed is True

    raw_response = _JsonBoundaryResponse({"id": "response-id"})
    client._open_provider = mock.Mock(return_value=raw_response)  # type: ignore[method-assign]
    assert client._send_raw(agent, "responses", {"model": agent.model}) == {
        "id": "response-id"
    }
    assert raw_response.json_reads == 1
    assert raw_response.closed is True

    upload_response = _JsonBoundaryResponse({"id": "file-id"})
    client._open_provider = mock.Mock(return_value=upload_response)  # type: ignore[method-assign]
    assert client._batch_upload(agent, b'{}\n') == "file-id"
    assert upload_response.json_reads == 1
    assert upload_response.closed is True

    batch_response = _JsonBoundaryResponse({"id": "batch-id"})
    client._open_provider = mock.Mock(return_value=batch_response)  # type: ignore[method-assign]
    assert client._batch_json(agent, "GET", "/batches/batch-id") == {"id": "batch-id"}
    assert batch_response.json_reads == 1
    assert batch_response.closed is True
