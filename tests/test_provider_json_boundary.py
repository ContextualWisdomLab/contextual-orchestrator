"""Regression coverage for the provider JSON trust boundary.

Provider-controlled structured responses are bounded before parsing, decoded as
strict UTF-8 JSON objects, and converted to stable errors that do not retain the
untrusted document in an exception cause. Validated HTTPS connections carry the
request path into the response wrapper so existing model-client call sites gain
the boundary without import-time mutation or duplicated parsing policy. Batch
output file content remains strict JSON Lines rather than a single JSON object.
"""

from __future__ import annotations

import http.client
import json
import ssl
from unittest import mock

import pytest

from contextual_orchestrator.orchestrator import ModelAgent, ModelClient
from contextual_orchestrator.provider_transport import (
    _PinnedHTTPSConnection,
    _ProviderHTTPResponse,
    _is_batch_output_content_path,
)


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


def _provider_agent() -> ModelAgent:
    """Return one two-word-ID HTTPS agent suitable for transport-unit seams."""
    return ModelAgent(
        id="provider_agent",
        model="provider-model",
        base_url="https://provider.example",
        credential_key="NVIDIA_NIM_API_KEY",
    )


def _path_aware_wrapper(payload: bytes, path: str) -> tuple[_ProviderHTTPResponse, _ByteResponse, mock.Mock]:
    """Return one response wrapper carrying the validated provider request path."""
    response = _ByteResponse(payload)
    connection = mock.Mock()
    connection._provider_request_path = path
    return _ProviderHTTPResponse(response, connection, max_bytes=4096), response, connection


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


def test_pinned_https_connection_records_response_contract_path() -> None:
    """The exact validated request target accompanies its later response wrapper."""
    connection = _PinnedHTTPSConnection(
        "provider.example",
        "203.0.113.10",
        443,
        1.0,
        ssl.create_default_context(),
    )

    with mock.patch.object(http.client.HTTPSConnection, "request") as parent_request:
        connection.request(
            "POST",
            "/v1/chat/completions?trace=one",
            headers={"Authorization": "Bearer reviewed-secret"},
        )

    assert connection._provider_request_path == "/v1/chat/completions?trace=one"
    parent_request.assert_called_once()


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/v1/files/file-output/content", True),
        ("/files/file-output/content?download=1", True),
        ("/v1/files", False),
        ("/v1/chat/completions", False),
        ("/v1/files/file-output/metadata", False),
    ],
)
def test_batch_output_path_classification_is_narrow(path: str, expected: bool) -> None:
    """Only the exact file-content suffix receives JSON Lines semantics."""
    assert _is_batch_output_content_path(path) is expected


def test_model_client_json_object_paths_fail_closed_through_transport() -> None:
    """Every structured provider path redacts malformed response documents."""
    client = ModelClient()
    agent = _provider_agent()
    malformed = b'{"secret":"private-provider-document",'

    wrappers = [
        _path_aware_wrapper(malformed, "/v1/chat/completions")[0],
        _path_aware_wrapper(malformed, "/v1/responses")[0],
        _path_aware_wrapper(malformed, "/v1/files")[0],
        _path_aware_wrapper(malformed, "/v1/batches/batch-id")[0],
    ]
    calls = [
        lambda: client._send(agent, {"model": agent.model}),
        lambda: client._send_raw(agent, "responses", {"model": agent.model}),
        lambda: client._batch_upload(agent, b"{}\n"),
        lambda: client._batch_json(agent, "GET", "/batches/batch-id"),
    ]

    for wrapper, call in zip(wrappers, calls, strict=True):
        client._open_provider = mock.Mock(return_value=wrapper)  # type: ignore[method-assign]
        with pytest.raises(RuntimeError, match="provider JSON response is malformed") as error:
            call()
        assert error.value.__cause__ is None
        assert "private-provider-document" not in str(error.value)


def test_model_client_json_object_paths_preserve_valid_results() -> None:
    """The shared strict boundary preserves existing structured response semantics."""
    client = ModelClient()
    agent = _provider_agent()

    wrapper, _, _ = _path_aware_wrapper(
        json.dumps(
            {
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"total_tokens": 1},
            }
        ).encode("utf-8"),
        "/v1/chat/completions",
    )
    client._open_provider = mock.Mock(return_value=wrapper)  # type: ignore[method-assign]
    assert client._send(agent, {"model": agent.model}) == "ok"

    wrapper, _, _ = _path_aware_wrapper(b'{"id":"response-id"}', "/v1/responses")
    client._open_provider = mock.Mock(return_value=wrapper)  # type: ignore[method-assign]
    assert client._send_raw(agent, "responses", {"model": agent.model}) == {
        "id": "response-id"
    }

    wrapper, _, _ = _path_aware_wrapper(b'{"id":"file-id"}', "/v1/files")
    client._open_provider = mock.Mock(return_value=wrapper)  # type: ignore[method-assign]
    assert client._batch_upload(agent, b"{}\n") == "file-id"

    wrapper, _, _ = _path_aware_wrapper(b'{"id":"batch-id"}', "/v1/batches/batch-id")
    client._open_provider = mock.Mock(return_value=wrapper)  # type: ignore[method-assign]
    assert client._batch_json(agent, "GET", "/batches/batch-id") == {"id": "batch-id"}


def test_batch_output_path_preserves_strict_json_lines_and_blank_separators() -> None:
    """Batch output remains line-addressable while harmless blank rows are ignored."""
    wrapper, _, _ = _path_aware_wrapper(
        b'{"custom_id":"first","value":1}\n\n{"custom_id":"second","value":2}\n',
        "/v1/files/file-output/content",
    )

    rows = [json.loads(line) for line in wrapper.read().decode("utf-8").splitlines()]
    assert rows == [
        {"custom_id": "first", "value": 1},
        {"custom_id": "second", "value": 2},
    ]


@pytest.mark.parametrize(
    "payload",
    [
        b'{"custom_id":"private-row","value":1,"value":2}\n',
        b'{"custom_id":"\xffprivate-row"}\n',
        b"[]\n",
        b"\n \t\n",
    ],
)
def test_batch_output_json_lines_reject_malformed_or_non_object_rows(payload: bytes) -> None:
    """Invalid JSONL fails before later row parsing can retain provider content."""
    wrapper, response, connection = _path_aware_wrapper(
        payload,
        "/v1/files/file-output/content?download=1",
    )

    with pytest.raises(RuntimeError, match="provider JSON Lines response is malformed") as error:
        with wrapper:
            wrapper.read()

    assert error.value.__cause__ is None
    assert "private-row" not in str(error.value)
    assert response.closed is True
    connection.close.assert_called_once_with()


def test_path_aware_partial_read_retains_bounded_byte_semantics() -> None:
    """Explicit partial reads remain byte-oriented and are never parsed prematurely."""
    wrapper, _, _ = _path_aware_wrapper(b'{"value":1}', "/v1/chat/completions")
    assert wrapper.read(2) == b'{"'


def test_path_aware_negative_read_normalizes_complete_document() -> None:
    """A negative read amount means full-document validation, matching HTTPResponse."""
    wrapper, _, _ = _path_aware_wrapper(b'{ "value" : 1 }', "/v1/chat/completions")
    assert wrapper.read(-1) == b'{"value":1}'


def test_empty_request_path_preserves_byte_oriented_test_seam() -> None:
    """An uncaptured test seam never gains provider-document authority accidentally."""
    response = _ByteResponse(b"not-json")
    connection = mock.Mock()
    connection._provider_request_path = ""
    wrapper = _ProviderHTTPResponse(response, connection, max_bytes=512)

    assert wrapper.read() == b"not-json"
