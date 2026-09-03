"""HTTP regression for caller-safe request-size detail on capability routes."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

from contextual_orchestrator import ModelAgent, TaskOrchestrator
from contextual_orchestrator.orchestrator import ProviderRequestTooLargeError
from contextual_orchestrator.server import SecurityConfig, build_server


def _post_error(port: int, token: str) -> tuple[int, dict[str, object]]:
    """POST one image request and decode the expected HTTP error envelope."""
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/images/generations",
        data=json.dumps({"model": "image-model", "prompt": "large image"}).encode("utf-8"),
        headers={
            "authorization": f"Bearer {token}",
            "content-type": "application/json",
            "connection": "close",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            raise AssertionError(f"request unexpectedly succeeded with {response.status}")
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_capability_413_preserves_structured_provider_detail() -> None:
    """Capability 413 must retain typed provider evidence through RequestError."""
    orchestrator = TaskOrchestrator(
        [ModelAgent("image_worker", "image-model", tags=("image",))]
    )

    def reject_capability(*_args: object, **_kwargs: object) -> object:
        """Raise the typed error produced after capability request-size exhaustion."""
        raise ProviderRequestTooLargeError(
            "request body exceeds every eligible provider limit",
            agent_id="image_worker",
            model="image-model",
            provider_status=413,
            transport="passthrough",
        )

    orchestrator.proxy_capability = reject_capability  # type: ignore[method-assign]
    token = "capability_detail_token"
    server = build_server(
        orchestrator,
        port=0,
        security=SecurityConfig(auth_token=token),
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        status, body = _post_error(server.server_address[1], token)
    finally:
        server.shutdown()

    assert status == 413
    error = body["error"]
    assert isinstance(error, dict)
    assert error["code"] == "request_too_large"
    detail = error["detail"]
    assert isinstance(detail, dict)
    assert "request_id" in detail
    assert detail["agent_id"] == "image_worker"
    assert detail["model"] == "image-model"
    assert detail["provider_status"] == 413
    assert detail["retryable"] is False
    assert detail["transport"] == "passthrough"
