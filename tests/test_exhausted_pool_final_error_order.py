"""An exhausted orchestrator/free pool surfaces an order-independent final error.

Noema review evidence (2026-09-16..21) showed review requests ending as
``400 invalid_request_error`` after earlier candidates had timed out, simply
because the last candidate answered 400. A caller treats 400 as a permanent
request fault and does not retry, while the transient 504s say the review is
retryable. The final surface must not depend on which candidate happened to
fail last; an all-400 pool still reports 400.
"""

from __future__ import annotations

import io
import json
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.credentials import (  # noqa: E402
    InMemoryCredentialBackend,
    register_credential,
    set_backend,
)
from contextual_orchestrator.orchestrator import ModelClient  # noqa: E402
from contextual_orchestrator.server import SecurityConfig, build_server  # noqa: E402

_TOKEN = "exhausted_pool_final_error_token"  # noqa: S105
_TAGS = ("cost:free", "reasoning", "writing", "planning", "coding", "verification")
_MODELS = ("vendor/a", "vendor/b", "vendor/c")


def _serve(monkeypatch, statuses: tuple[int, int, int]) -> tuple[int, str | None, list[str]]:
    """Send one orchestrator/free request where each model fails with its status."""
    set_backend(InMemoryCredentialBackend())
    register_credential("NVIDIA_NIM_API_KEY", "synthetic-not-a-key")
    by_model = dict(zip(_MODELS, statuses))
    calls: list[str] = []

    def failing_open(self, request, destination=None, *, timeout=None):
        model = json.loads(request.data)["model"]
        calls.append(model)
        body = json.dumps({"error": {"message": "synthetic", "type": "synthetic"}}).encode()
        raise urllib.error.HTTPError(
            request.full_url, by_model[model], "synthetic", {"Content-Type": "application/json"}, io.BytesIO(body)
        )

    monkeypatch.setattr(ModelClient, "_validate_provider", lambda self, agent: None)
    monkeypatch.setattr(ModelClient, "_open_provider", failing_open)
    agents = [
        ModelAgent(
            f"agent_{model.rsplit('/', 1)[-1]}",
            model,
            base_url="https://provider.invalid/v1",
            api_key_env="NVIDIA_NIM_API_KEY",
            tags=_TAGS,
            priority=priority,
        )
        for priority, model in zip((30, 20, 10), _MODELS)
    ]
    server = build_server(
        TaskOrchestrator(agents, tool_retry_attempts=0, rate_limit_wait_seconds=0),
        port=0,
        security=SecurityConfig(auth_token=_TOKEN),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    request = urllib.request.Request(
        f"http://127.0.0.1:{server.server_address[1]}/v1/chat/completions",
        data=json.dumps(
            {"model": TaskOrchestrator.FREE_MODEL, "messages": [{"role": "user", "content": "review this change"}]}
        ).encode(),
        headers={"content-type": "application/json", "authorization": f"Bearer {_TOKEN}", "connection": "close"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            response.read()
            return response.status, None, calls
    except urllib.error.HTTPError as exc:
        with exc:
            return exc.code, json.loads(exc.read())["error"]["code"], calls
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
        set_backend(None)


@pytest.mark.parametrize(
    "statuses, expected",
    [
        ((504, 504, 400), (504, "provider_timeout")),
        ((400, 504, 504), (504, "provider_timeout")),
        ((504, 400, 504), (504, "provider_timeout")),
        ((429, 400, 400), (429, "provider_rate_limited")),
        ((400, 429, 400), (429, "provider_rate_limited")),
        ((504, 400, 413), (504, "provider_timeout")),
    ],
)
def test_mixed_exhaustion_surfaces_the_retryable_failure_whatever_the_order(monkeypatch, statuses, expected) -> None:
    status, code, calls = _serve(monkeypatch, statuses)

    assert sorted(calls) == sorted(_MODELS)
    assert (status, code) == expected


def test_all_request_rejections_still_surface_400(monkeypatch) -> None:
    status, code, calls = _serve(monkeypatch, (400, 400, 400))

    assert sorted(calls) == sorted(_MODELS)
    assert (status, code) == (400, "invalid_request_error")


def test_all_size_rejections_still_surface_413(monkeypatch) -> None:
    status, code, calls = _serve(monkeypatch, (413, 413, 413))

    assert sorted(calls) == sorted(_MODELS)
    assert (status, code) == (413, "request_too_large")
