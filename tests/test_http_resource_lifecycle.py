"""Test-owned HTTP resources close on success and decoding failures."""

import io
import json
import urllib.error

import pytest

from test_actions_model_fallback import _post
from test_openai_passthrough import _post as passthrough_post
from test_agent_pool_db import _call as pool_call
from test_true_streaming import _CapturingSSEProvider, _FakeSSEProvider
from contextual_orchestrator import ModelAgent, ToolFallbackStoppedError
from contextual_orchestrator.orchestrator import ModelClient
from contextual_orchestrator.orchestrator import ProviderRequestTooLargeError
from contextual_orchestrator.provider_errors import ProviderUpstreamError


@pytest.mark.parametrize("status_code", [401, 429, 413, 409])
@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_retry_boundary_closes_final_response(monkeypatch, status_code, cleanup_fails):
    """Final classification preserves meaning before releasing its response."""
    response_body = io.BytesIO(
        b'{"error":{"code":"tool_execution_stopped"}}'
        if status_code == 409 else b'{}'
    )
    response_error = urllib.error.HTTPError(
        "https://provider.example/v1", status_code, "error", {}, response_body
    )
    client = ModelClient(max_retries=0)
    original_close = response_error.close
    if cleanup_fails:
        def failing_close():
            """A cleanup failure must not replace the safe classified error."""
            original_close()
            raise OSError("private cleanup diagnostic")
        monkeypatch.setattr(response_error, "close", failing_close)

    def raise_response(*args, **kwargs):
        """Simulate the transport handing ownership to the retry boundary."""
        raise response_error

    monkeypatch.setattr(client, "_send", raise_response)
    expected = (ToolFallbackStoppedError if status_code == 409 else
                ProviderRequestTooLargeError if status_code == 413 else ProviderUpstreamError)
    try:
        with pytest.raises(expected):
            client._send_with_retry(
                ModelAgent("worker_agent", "model_name", base_url="https://provider.example/v1"), {}
            )
        assert response_body.closed
    finally:
        original_close()


@pytest.mark.parametrize("second_fails", [False, True])
def test_retry_closes_previous_response_before_backoff(monkeypatch, second_fails):
    """Retry delay starts only after consuming and closing the failed response."""
    first_error = urllib.error.HTTPError("https://provider.example/v1", 429, "retry", {}, io.BytesIO(b"{}"))
    final_error = urllib.error.HTTPError("https://provider.example/v1", 401, "stop", {}, io.BytesIO(b"{}"))
    client = ModelClient(max_retries=1)
    attempted_calls = []
    observed_delays = []

    def send_attempt(*args, **kwargs):
        """Return a success or distinct terminal error on the second attempt."""
        attempted_calls.append(len(attempted_calls) + 1)
        if len(attempted_calls) == 1:
            raise first_error
        if second_fails:
            raise final_error
        return "delivered answer"

    def check_backoff(delay):
        """Assert closure before waiting without an actual wall-clock delay."""
        observed_delays.append(delay)
        assert first_error.closed

    monkeypatch.setattr(client, "_send", send_attempt)
    monkeypatch.setattr(client, "_backoff_delay", lambda attempt: 0.125)
    monkeypatch.setattr(client, "_sleep", check_backoff)
    try:
        agent = ModelAgent("worker_agent", "model_name", base_url="https://provider.example/v1")
        if second_fails:
            with pytest.raises(ProviderUpstreamError) as captured:
                client._send_with_retry(agent, {})
            assert captured.value.provider_status == 401
            assert final_error.closed
        else:
            assert client._send_with_retry(agent, {}) == "delivered answer"
        assert attempted_calls == [1, 2]
        assert observed_delays == [0.125]
    finally:
        first_error.close()
        final_error.close()


@pytest.mark.parametrize("provider_type", [_FakeSSEProvider, _CapturingSSEProvider])
def test_provider_context_closes_listening_socket(provider_type):
    """Leaving either provider context releases its real listening socket."""
    provider = provider_type([])
    try:
        with provider:
            assert provider._server.socket.fileno() >= 0
        assert provider._server.socket.fileno() == -1
        assert not provider._thread.is_alive()
    finally:
        provider._server.server_close()
        provider._thread.join()


@pytest.mark.parametrize("body_bytes", [b'{"error":"unavailable"}', b'not-json'])
@pytest.mark.parametrize("helper_name", ["actions", "passthrough", "agent_pool"])
def test_post_closes_error_body_even_when_decoding_fails(monkeypatch, body_bytes, helper_name):
    """The shared HTTP helper owns error bodies, including invalid JSON."""
    body_stream = io.BytesIO(body_bytes)
    response_error = urllib.error.HTTPError(
        "http://127.0.0.1/", 502, "Bad Gateway", {}, body_stream
    )

    def raise_response_error(*args, **kwargs):
        raise response_error

    monkeypatch.setattr("urllib.request.urlopen", raise_response_error)
    def call_helper():
        """Exercise each existing helper with its public argument contract."""
        if helper_name == "actions":
            return _post(1, {})
        if helper_name == "agent_pool":
            return pool_call("http://127.0.0.1/", "POST", "test_token", {})
        return passthrough_post("http://127.0.0.1/", {}, "test_token")

    try:
        if body_bytes == b'not-json':
            with pytest.raises(json.JSONDecodeError):
                call_helper()
        else:
            expected = (502, {"error": "unavailable"})
            if helper_name == "actions":
                expected += ("application/json",)
            assert call_helper() == expected
        assert body_stream.closed
    finally:
        response_error.close()


@pytest.mark.parametrize("tool_stopped", [False, True])
def test_stream_cleanup_failure_preserves_safe_provider_error(monkeypatch, tool_stopped):
    """A failing response closer must not replace the classified stream error."""
    response_error = urllib.error.HTTPError(
        "http://127.0.0.1/", 409 if tool_stopped else 500, "error", {},
        io.BytesIO(b'{"error":{"code":"tool_execution_stopped"}}' if tool_stopped else b"{}")
    )
    original_close = response_error.close

    def failing_close():
        original_close()
        raise OSError("private cleanup diagnostic")

    def raise_response_error(*args, **kwargs):
        raise response_error

    monkeypatch.setattr(response_error, "close", failing_close)
    client = ModelClient()
    monkeypatch.setattr(client, "_open_provider", raise_response_error)
    try:
        expected_error = ToolFallbackStoppedError if tool_stopped else ProviderUpstreamError
        with pytest.raises(expected_error) as captured:
            list(client._stream_send(
                ModelAgent("worker_agent", "model_name", base_url="http://127.0.0.1"), {}
            ))
        if not tool_stopped:
            assert captured.value.client_status == 502
        assert "private cleanup diagnostic" not in str(captured.value)
    finally:
        original_close()
