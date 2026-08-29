"""Provider failure taxonomy: classification, redaction, and API error surface.

Every upstream provider/model failure must reach the caller as one classified,
OpenAI-compatible error — naming the model, the cause family, and whether a
retry can help — instead of collapsing into a generic ``internal_error``.
"""

from __future__ import annotations

import io
import json
import socket
import ssl
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.orchestrator import ModelClient, is_transient_error  # noqa: E402
from contextual_orchestrator.provider_errors import (  # noqa: E402
    MAX_PROVIDER_ERROR_BODY_BYTES,
    MAX_SAFE_MESSAGE_CHARS,
    PROVIDER_STATUS_SURFACES,
    ProviderUpstreamError,
    classify_provider_failure,
    safe_provider_message,
)
from contextual_orchestrator.server import SecurityConfig, build_server  # noqa: E402


def _http_error(code: int, body: bytes | None = None) -> urllib.error.HTTPError:
    payload = io.BytesIO(body) if body is not None else None
    return urllib.error.HTTPError(
        "https://provider.example/chat/completions", code, "error", None, payload
    )


def _body_http_error(code: int, payload: dict) -> urllib.error.HTTPError:
    return _http_error(code, json.dumps(payload).encode("utf-8"))


# -- message redaction --------------------------------------------------------


def test_safe_message_prefers_nested_provider_error_fields() -> None:
    """``error.message`` / ``error.code`` / top-level fields are the only pass-through."""
    nested = safe_provider_message(_body_http_error(400, {"error": {"message": "max_tokens too large"}}))
    assert nested == "max_tokens too large"
    coded = safe_provider_message(_body_http_error(400, {"error": {"code": "context_length_exceeded"}}))
    assert coded == "context_length_exceeded"
    plain_string = safe_provider_message(_body_http_error(400, {"error": "invalid api key"}))
    assert plain_string is None
    top_level = safe_provider_message(_body_http_error(429, {"message": "rate limit reached"}))
    assert top_level == "rate limit reached"
    detail = safe_provider_message(_body_http_error(422, {"detail": "validation failed"}))
    assert detail == "validation failed"


def test_safe_message_hides_unparseable_bodies_and_urls() -> None:
    """Non-JSON bodies return None so URLs/reasons never leak through fallback text."""
    assert safe_provider_message(_http_error(500, b"upstream-secret http://10.0.0.9/internal")) is None
    assert safe_provider_message(_http_error(502)) is None


def test_safe_message_reads_only_a_bounded_provider_body() -> None:
    """Untrusted provider bodies are bounded before JSON parsing."""

    class RecordingBody(io.BytesIO):
        requested_size: int | None = None

        def read(self, size: int = -1) -> bytes:
            self.requested_size = size
            return super().read(size)

    body = RecordingBody(b"{}")
    error = urllib.error.HTTPError(
        "https://provider.example/chat/completions", 500, "error", None, body
    )
    assert safe_provider_message(error) is None
    assert body.requested_size == MAX_PROVIDER_ERROR_BODY_BYTES + 1


def test_safe_message_reuses_body_after_retryability_inspection() -> None:
    """Tool-stop and caller-safe classification share one bounded body read."""
    error = _body_http_error(401, {"error": {"message": "invalid credential"}})

    assert is_transient_error(error) is False
    assert safe_provider_message(error) == "invalid credential"


def test_safe_message_collapses_control_characters_and_bounds_length() -> None:
    """Control characters cannot smuggle log or header content; length is bounded."""
    long = safe_provider_message(
        _body_http_error(400, {"error": {"message": "x" * 500}})
    )
    assert long is not None
    assert len(long) == MAX_SAFE_MESSAGE_CHARS
    raw = "line1\nline2\ttabbed\x00nul\x7fdel\x85next"
    collapsed = safe_provider_message(_body_http_error(400, {"error": {"message": raw}}))
    assert collapsed is not None
    assert all(control not in collapsed for control in ("\n", "\x00", "\x7f", "\x85"))
    assert "\t" in collapsed  # tab is preserved for readability


def test_safe_message_non_http_exception_uses_first_arg_text() -> None:
    """Generic exceptions keep their own first argument as bounded context."""
    assert safe_provider_message(RuntimeError("plain failure")) == "plain failure"
    assert safe_provider_message(ValueError()) == "ValueError"


# -- classification table ------------------------------------------------------


def test_classification_maps_every_upstream_status_to_openai_surface() -> None:
    """Each upstream status yields its documented client status/code/retryable."""
    expected = {
        400: (400, "invalid_request_error", False),
        401: (401, "authentication_error", False),
        402: (402, "payment_required", False),
        403: (403, "permission_error", False),
        404: (404, "model_not_found", False),
        408: (504, "provider_timeout", True),
        409: (409, "conflict", True),
        413: (413, "request_too_large", False),
        422: (400, "invalid_request_error", False),
        425: (429, "rate_limit_exceeded", True),
        429: (429, "rate_limit_exceeded", True),
        500: (502, "api_error", True),
        503: (503, "service_unavailable", True),
        504: (504, "provider_timeout", True),
        529: (503, "service_unavailable", True),
    }
    for status, surface in expected.items():
        assert PROVIDER_STATUS_SURFACES[status] == surface, f"status {status}"
        classified = classify_provider_failure(_http_error(status), agent_id="a", model="m")
        assert isinstance(classified, ProviderUpstreamError)
        assert classified.client_status == surface[0], f"status {status}"
        assert classified.error_code == surface[1], f"status {status}"
        assert classified.retryable == surface[2], f"status {status}"
        assert classified.provider_status == status
        assert classified.model == "m"


def test_classification_handles_network_tls_and_unknown_causes() -> None:
    """Network, TLS, unmapped-status, and generic failures each classify distinctly."""
    network = classify_provider_failure(urllib.error.URLError("dns"), agent_id="a", model="m")
    assert network.error_code == "provider_connection_error"
    assert network.client_status == 502 and network.retryable
    for exc in (socket.timeout("slow"), TimeoutError("deadline"), ConnectionError("reset")):
        assert classify_provider_failure(exc, agent_id="a", model="m").retryable

    temporary_dns = socket.gaierror(socket.EAI_AGAIN, "temporary DNS failure")
    wrapped_dns = RuntimeError("provider host could not be resolved")
    wrapped_dns.__cause__ = temporary_dns
    for exc in (temporary_dns, wrapped_dns):
        dns = classify_provider_failure(exc, agent_id="a", model="m")
        assert dns.error_code == "provider_connection_error"
        assert dns.retryable

    permanent_dns = classify_provider_failure(
        socket.gaierror(socket.EAI_NONAME, "unknown host"), agent_id="a", model="m"
    )
    assert permanent_dns.error_code == "provider_connection_error"
    assert not permanent_dns.retryable

    none_failure = classify_provider_failure(None, agent_id="a", model="m")
    assert none_failure.error_code == "api_error"
    assert not none_failure.retryable

    cert = ssl.SSLCertVerificationError("bad chain")
    tls_verify = classify_provider_failure(cert, agent_id="a", model="m")
    assert tls_verify.error_code == "tls_verification_failed"
    assert not tls_verify.retryable

    handshake = ssl.SSLError("handshake eof")
    assert classify_provider_failure(handshake, agent_id="a", model="m").retryable

    unmapped = classify_provider_failure(_http_error(418), agent_id="a", model="m")
    assert unmapped.error_code == "api_error"
    assert not unmapped.retryable

    generic = classify_provider_failure(RuntimeError("internal"), agent_id="agent_x", model="m")
    assert generic.error_code == "api_error"
    assert "internal" not in str(generic)
    assert str(generic).endswith("request failed")

    original = ProviderUpstreamError(
        agent_id="a",
        model="m",
        error_code="rate_limit_exceeded",
        message="kept",
        client_status=429,
        retryable=True,
    )
    assert classify_provider_failure(original, agent_id="b", model="n") is original


def test_capability_dispatch_preserves_last_classified_provider_failure() -> None:
    """Non-chat capability exhaustion keeps the actionable upstream taxonomy."""
    orchestrator = TaskOrchestrator(
        [ModelAgent("image_agent", "image-model", tags=("image",))]
    )
    expected = ProviderUpstreamError(
        agent_id="image_agent",
        model="image-model",
        error_code="rate_limit_exceeded",
        message="provider rate limit reached",
        client_status=429,
        retryable=True,
    )
    def fail(*_args: object, **_kwargs: object) -> dict:
        raise expected

    orchestrator.client.proxy_send = fail  # type: ignore[method-assign]

    try:
        orchestrator.proxy_capability(
            {"prompt": "demo"}, capability="image", endpoint="images/generations"
        )
    except ProviderUpstreamError as raised:
        assert raised is expected
    else:
        raise AssertionError("classified capability failure was not raised")


def test_binary_passthrough_classifies_provider_transport_failure() -> None:
    """Binary capability failures retain the same caller-facing taxonomy."""
    client = ModelClient(max_retries=0)
    agent = ModelAgent("audio_agent", "audio-model", base_url="https://provider.example/v1")
    upstream = _http_error(503)
    with patch.object(client, "_validate_provider", return_value=None), patch.object(
        client, "_open_provider", side_effect=upstream
    ):
        try:
            client.proxy_send_bytes(agent, "audio/speech", {"input": "hello"})
        except ProviderUpstreamError as raised:
            assert raised.error_code == "service_unavailable"
            assert raised.client_status == 503
            assert raised.provider_status == 503
            assert raised.transport == "passthrough"
        else:  # pragma: no cover
            raise AssertionError("binary provider failure must be classified")


def test_detail_and_transport_are_preserved_for_callers() -> None:
    """The structured detail names agent/model/status/retryability/transport."""
    classified = classify_provider_failure(
        _http_error(429), agent_id="worker_agent", model="gpt-x", transport="passthrough"
    )
    assert classified.detail == {
        "agent_id": "worker_agent",
        "model": "gpt-x",
        "provider_status": 429,
        "retryable": True,
        "transport": "passthrough",
    }
    assert "HTTP 429" in str(classified)


# -- client wiring -------------------------------------------------------------


class _StatusFailureClient(ModelClient):
    """Raises one fixed HTTP status from every transport send."""

    def __init__(self, code: int) -> None:
        super().__init__(max_retries=2, retry_backoff=0.0)
        self.code = code
        self.attempts = 0

    def _send(self, agent: ModelAgent, payload: dict, destination=None) -> str:  # type: ignore[override]
        self.attempts += 1
        raise _http_error(self.code)

    def _send_raw(self, agent: ModelAgent, endpoint: str, payload: dict, destination=None):  # type: ignore[override]
        self.attempts += 1
        raise _http_error(self.code)


def test_chat_retry_layer_surfaces_classified_rate_limit() -> None:
    """A 429 exhausts retries then raises rate_limit_exceeded with retryable=True."""
    client = _StatusFailureClient(429)
    agent = ModelAgent("worker_agent", "gpt-x", base_url="https://provider.example/v1")
    with patch.object(client, "_validate_provider", lambda unused: None):
        try:
            client._send_with_retry(agent, {"model": "gpt-x"})
        except ProviderUpstreamError as exc:
            assert exc.error_code == "rate_limit_exceeded"
            assert exc.client_status == 429
            assert exc.provider_status == 429
            assert exc.retryable is True
        else:  # pragma: no cover
            raise AssertionError("classified failure must propagate")
    assert client.attempts == 3  # initial + 2 retries


def test_passthrough_retry_layer_surfaces_model_not_found_without_retry() -> None:
    """A 404 on passthrough fails immediately as model_not_found."""
    client = _StatusFailureClient(404)
    agent = ModelAgent("proxy_agent", "missing-model", base_url="https://provider.example/v1")
    with patch.object(client, "_validate_provider", lambda unused: None):
        try:
            client._send_raw_with_retry(agent, "responses", {})
        except ProviderUpstreamError as exc:
            assert exc.error_code == "model_not_found"
            assert exc.transport == "passthrough"
            assert client.attempts == 1  # caller errors are never retried
        else:  # pragma: no cover
            raise AssertionError("classified failure must propagate")


def test_invoke_preserves_final_classified_failure_across_candidates() -> None:
    """Failover still runs, but an all-failed pool surfaces the last cause.

    The fake client raises exactly what ``ModelClient._send_with_retry`` now
    produces — a classified ``ProviderUpstreamError`` — so this exercises the
    real boundary contract between the transport layer and agent failover.
    """

    def _rate_limited(agent: ModelAgent) -> ProviderUpstreamError:
        return classify_provider_failure(_http_error(429), agent_id=agent.id, model=agent.model)

    class RateLimited(ModelClient):
        def chat(self, agent: ModelAgent, messages: list, temperature: float = 0.2) -> str:  # type: ignore[override]
            raise _rate_limited(agent)

    agents = [
        ModelAgent("primary_worker", "mock-a", tags=("reasoning",)),
        ModelAgent("backup_worker", "mock-b", tags=("reasoning",)),
    ]
    orchestrator = TaskOrchestrator(agents, client=RateLimited())
    orchestrator._triage_fn = lambda text: False  # single-step route accounting
    try:
        orchestrator.route_once([{"role": "user", "content": "route this"}])
    except ProviderUpstreamError as exc:
        assert exc.error_code == "rate_limit_exceeded"
        assert exc.client_status == 429
        assert exc.agent_id in {"primary_worker", "backup_worker"}
    else:  # pragma: no cover
        raise AssertionError("the final classified failure must survive failover")


def test_invoke_does_not_retry_nonretryable_provider_failure_on_same_agent() -> None:
    """A classified auth failure advances to the backup without repeating it."""

    class AuthThenBackup(ModelClient):
        def __init__(self) -> None:
            super().__init__()
            self.calls: list[str] = []

        def chat(self, agent: ModelAgent, messages: list, temperature: float = 0.2) -> str:  # type: ignore[override]
            self.calls.append(agent.id)
            if agent.id == "primary_worker":
                raise classify_provider_failure(
                    _http_error(401), agent_id=agent.id, model=agent.model
                )
            return "backup answer"

    client = AuthThenBackup()
    agents = [
        ModelAgent("primary_worker", "mock-a", tags=("reasoning",), priority=2),
        ModelAgent("backup_worker", "mock-b", tags=("reasoning",), priority=1),
    ]
    orchestrator = TaskOrchestrator(agents, client=client, tool_retry_attempts=2)
    orchestrator._triage_fn = lambda text: False

    result = orchestrator.route_once([{"role": "user", "content": "route this"}])

    assert result["answer"] == "backup answer"
    assert client.calls[0:2] == ["primary_worker", "backup_worker"]
    assert client.calls.count("primary_worker") == 1


# -- server error surface ------------------------------------------------------


class _UpstreamDown(ModelClient):
    """Chat client whose provider always answers 429, classified as the real layer does."""

    def chat(self, agent: ModelAgent, messages: list, temperature: float = 0.2) -> str:  # type: ignore[override]
        raise classify_provider_failure(_http_error(429), agent_id=agent.id, model=agent.model)


def _post(url: str, payload: dict, token: str) -> tuple[int, dict]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"content-type": "application/json", "authorization": f"Bearer {token}", "connection": "close"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_chat_completions_returns_openai_compatible_rate_limit_error() -> None:
    """A throttled model answers 429/rate_limit_exceeded, never internal_error."""
    orchestrator = TaskOrchestrator(
        [ModelAgent("worker_agent", "gpt-x", tags=("reasoning",))],
        client=_UpstreamDown(),
    )
    orchestrator._triage_fn = lambda text: False
    token = "taxonomy_token"
    server = build_server(orchestrator, port=0, security=SecurityConfig(auth_token=token))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        status, body = _post(
            f"http://127.0.0.1:{server.server_address[1]}/v1/chat/completions",
            {"model": "gpt-x", "messages": [{"role": "user", "content": "hello"}]},
            token,
        )
    finally:
        server.shutdown()

    assert status == 429
    error = body["error"]
    assert error["code"] == "rate_limit_exceeded"
    assert "gpt-x" in error["message"] and "worker_agent" in error["message"]
    assert "Retry after a short delay" in error["message"]
    assert error["detail"]["provider_status"] == 429
    assert error["detail"]["model"] == "gpt-x"
    assert error["detail"]["retryable"] is True


def test_guidance_table_covers_every_documented_code() -> None:
    """Every classified code has caller guidance; unknown codes get a default."""
    from contextual_orchestrator import server as server_module

    codes = {surface[1] for surface in PROVIDER_STATUS_SURFACES.values()}
    codes.update({"tls_verification_failed", "tls_failure", "provider_connection_error"})
    for code in codes:
        assert code in server_module._PROVIDER_FAILURE_GUIDANCE, f"missing guidance for {code}"

    class UnknownCode(ProviderUpstreamError):
        pass

    exotic = UnknownCode(
        agent_id="a",
        model="m",
        error_code="exotic_future_code",
        message="unknown",
        client_status=500,
    )
    message = server_module._provider_upstream_message(exotic)
    assert "contact the operator" in message


def test_safe_message_discards_sensitive_provider_diagnostics() -> None:
    """Credentials, request content, URLs, and private topology never reach callers."""
    diagnostics = (
        "authorization: Bearer provider-secret-value",
        "prompt=private customer message",
        "request failed at http://10.0.0.9/internal",
        "token=abc123456789012345",
    )
    for diagnostic in diagnostics:
        error = _body_http_error(400, {"error": {"message": diagnostic}})
        assert safe_provider_message(error) is None
        classified = classify_provider_failure(error, agent_id="a", model="m")
        assert diagnostic not in str(classified)
        assert str(classified) == "provider rejected the request with HTTP 400"
