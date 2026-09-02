"""Per-model LLM request timeout admin surface: view/set/clear/restore.

Covers the org's admin-web-directive requirement (docs/product-goal-directive.md
in ContextualWisdomLab/.github) for operator visibility and control over
per-model LLM timeouts: units (seconds), priority (explicit override beats
the inherited client default), inheritance, input validation, audit history,
and the HTTP API contract -- plus the real wiring into ModelClient so a set
override actually changes the timeout used for outbound provider calls.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.credentials import register_credential  # noqa: E402
from contextual_orchestrator.orchestrator import (  # noqa: E402
    MAX_MODEL_TIMEOUT_SECONDS,
    MIN_MODEL_TIMEOUT_SECONDS,
    ModelClient,
    _validate_model_timeout_seconds,
)
from contextual_orchestrator.admin import ADMIN_HTML, ADMIN_TRANSLATIONS  # noqa: E402
from contextual_orchestrator.server import SecurityConfig, build_server  # noqa: E402

TOKEN = "model_timeout_token"


def _seed() -> list[ModelAgent]:
    return [ModelAgent("worker_agent", "gpt-example", tags=("coding",))]


# -- validation ----------------------------------------------------------------


@pytest.mark.parametrize("bad", [True, "90", None, float("nan"), float("inf"), 0, -1, 0.5, MAX_MODEL_TIMEOUT_SECONDS + 1])
def test_model_timeout_validation_rejects_bad_values(bad) -> None:
    with pytest.raises(ValueError):
        _validate_model_timeout_seconds(bad)


@pytest.mark.parametrize("good", [MIN_MODEL_TIMEOUT_SECONDS, 90, 120.5, MAX_MODEL_TIMEOUT_SECONDS])
def test_model_timeout_validation_accepts_boundary_values(good) -> None:
    assert _validate_model_timeout_seconds(good) == float(good)


# -- orchestrator-level CRUD + inheritance + audit ------------------------------


def test_effective_model_timeout_inherits_client_default_until_overridden() -> None:
    orchestrator = TaskOrchestrator(_seed(), client=ModelClient(timeout=77))
    assert orchestrator.effective_model_timeout("gpt-example") == 77.0
    listed = orchestrator.list_model_timeouts()
    assert listed == [
        {
            "model": "gpt-example",
            "effective_timeout_seconds": 77.0,
            "override_timeout_seconds": None,
            "default_timeout_seconds": 77.0,
            "source": "default",
        }
    ]


def test_set_model_timeout_overrides_and_records_audit_history() -> None:
    orchestrator = TaskOrchestrator(_seed())
    result = orchestrator.set_model_timeout("gpt-example", 150)
    assert result["source"] == "override"
    assert result["effective_timeout_seconds"] == 150.0
    assert result["override_timeout_seconds"] == 150.0
    assert result["audit_history"][0]["event_type"] == "model_timeout_set"
    assert result["audit_history"][0]["event_detail"] == {
        "model": "gpt-example",
        "previous_timeout_seconds": None,
        "timeout_seconds": 150.0,
    }
    assert orchestrator.effective_model_timeout("gpt-example") == 150.0

    # A second set records the prior override for the audit trail.
    second = orchestrator.set_model_timeout("gpt-example", 200)
    assert second["audit_history"][0]["event_detail"]["previous_timeout_seconds"] == 150.0


def test_clear_model_timeout_restores_default_and_records_audit_history() -> None:
    orchestrator = TaskOrchestrator(_seed(), client=ModelClient(timeout=90))
    orchestrator.set_model_timeout("gpt-example", 150)
    cleared = orchestrator.clear_model_timeout("gpt-example")
    assert cleared["source"] == "default"
    assert cleared["effective_timeout_seconds"] == 90.0
    assert cleared["override_timeout_seconds"] is None
    assert cleared["audit_history"][0] == {
        "created_at": cleared["audit_history"][0]["created_at"],
        "event_type": "model_timeout_cleared",
        "event_detail": {"model": "gpt-example", "previous_timeout_seconds": 150.0},
    }
    assert orchestrator.effective_model_timeout("gpt-example") == 90.0


def test_set_model_timeout_rejects_unknown_model() -> None:
    orchestrator = TaskOrchestrator(_seed())
    with pytest.raises(KeyError):
        orchestrator.set_model_timeout("no-such-model", 90)


def test_get_model_timeout_rejects_unknown_model() -> None:
    orchestrator = TaskOrchestrator(_seed())
    with pytest.raises(KeyError):
        orchestrator.get_model_timeout("no-such-model")


def test_clear_model_timeout_rejects_when_no_override_is_set() -> None:
    orchestrator = TaskOrchestrator(_seed())
    with pytest.raises(KeyError):
        orchestrator.clear_model_timeout("gpt-example")


def test_set_model_timeout_rejects_out_of_range_seconds() -> None:
    orchestrator = TaskOrchestrator(_seed())
    with pytest.raises(ValueError):
        orchestrator.set_model_timeout("gpt-example", -5)


# -- persistence -----------------------------------------------------------------


def test_model_timeout_overrides_persist_across_restart() -> None:
    with tempfile.TemporaryDirectory() as directory:
        database_path = os.path.join(directory, "model-timeouts.db")
        first = TaskOrchestrator(_seed(), state_db=database_path)
        first.set_model_timeout("gpt-example", 222)
        first.close()

        second = TaskOrchestrator(_seed(), state_db=database_path)
        assert second.effective_model_timeout("gpt-example") == 222.0
        second.clear_model_timeout("gpt-example")
        second.close()

        third = TaskOrchestrator(_seed(), state_db=database_path)
        assert third.effective_model_timeout("gpt-example") == 90.0
        third.close()


# -- real ModelClient wiring: an override changes the outbound call timeout ------


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> bool:
        return False

    def read(self) -> bytes:
        return self._body


def test_chat_call_uses_the_resolved_per_model_timeout() -> None:
    agent = ModelAgent(
        id="remote_agent",
        model="gpt-example",
        base_url="https://remote.example/v1",
        credential_key="REMOTE_API_KEY",
    )
    register_credential("REMOTE_API_KEY", "sk-test")
    orchestrator = TaskOrchestrator([agent])
    orchestrator.set_model_timeout("gpt-example", 111)
    captured_timeouts: list[float | None] = []

    def fake_open_provider(_request, _destination=None, *, timeout=None):
        captured_timeouts.append(timeout)
        return _FakeResponse({"choices": [{"message": {"content": "ok"}}]})

    with patch.object(orchestrator.client, "_validate_provider", return_value=None), patch.object(
        orchestrator.client, "_open_provider", side_effect=fake_open_provider
    ):
        orchestrator.client.chat(agent, [{"role": "user", "content": "hi"}])

    assert captured_timeouts == [111.0]


def test_chat_call_passes_no_timeout_override_when_none_is_configured() -> None:
    """No override => no ``timeout`` kwarg at all, byte-for-byte prior behavior."""
    agent = ModelAgent(
        id="remote_agent",
        model="gpt-example",
        base_url="https://remote.example/v1",
        credential_key="REMOTE_API_KEY",
    )
    register_credential("REMOTE_API_KEY", "sk-test")
    orchestrator = TaskOrchestrator([agent])
    captured_timeouts: list[float | None] = []

    def fake_open_provider(_request, _destination=None, *, timeout=None):
        captured_timeouts.append(timeout)
        return _FakeResponse({"choices": [{"message": {"content": "ok"}}]})

    with patch.object(orchestrator.client, "_validate_provider", return_value=None), patch.object(
        orchestrator.client, "_open_provider", side_effect=fake_open_provider
    ):
        orchestrator.client.chat(agent, [{"role": "user", "content": "hi"}])

    assert captured_timeouts == [None]


def test_stream_chat_uses_the_resolved_per_model_timeout() -> None:
    agent = ModelAgent(
        id="remote_agent",
        model="gpt-example",
        base_url="https://remote.example/v1",
        credential_key="REMOTE_API_KEY",
    )
    register_credential("REMOTE_API_KEY", "sk-test")
    orchestrator = TaskOrchestrator([agent])
    orchestrator.set_model_timeout("gpt-example", 333)
    captured_timeouts: list[float | None] = []

    class _StreamResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args) -> bool:
            return False

        def __iter__(self):
            return iter([b'data: {"choices":[{"delta":{"content":"hi"}}]}\n', b"data: [DONE]\n"])

    def fake_open_provider(_request, _destination=None, *, timeout=None):
        captured_timeouts.append(timeout)
        return _StreamResponse()

    with patch.object(orchestrator.client, "_validate_provider", return_value=None), patch.object(
        orchestrator.client, "_open_provider", side_effect=fake_open_provider
    ):
        list(orchestrator.client.stream_chat(agent, [{"role": "user", "content": "hi"}]))

    assert captured_timeouts == [333.0]


def test_bare_model_client_with_no_resolver_passes_no_timeout_override() -> None:
    """A standalone ModelClient (no TaskOrchestrator wiring) keeps prior behavior exactly."""
    agent = ModelAgent(
        id="remote_agent",
        model="gpt-example",
        base_url="https://remote.example/v1",
        credential_key="REMOTE_API_KEY",
    )
    register_credential("REMOTE_API_KEY", "sk-test")
    client = ModelClient()
    assert client.model_timeout_resolver is None
    captured_timeouts: list[float | None] = []

    def fake_open_provider(_request, _destination=None, *, timeout=None):
        captured_timeouts.append(timeout)
        return _FakeResponse({"choices": [{"message": {"content": "ok"}}]})

    with patch.object(client, "_validate_provider", return_value=None), patch.object(
        client, "_open_provider", side_effect=fake_open_provider
    ):
        client.chat(agent, [{"role": "user", "content": "hi"}])

    assert captured_timeouts == [None]


def test_wired_resolver_returns_none_for_a_model_with_no_override() -> None:
    """The resolver wired into ModelClient returns only overrides, never the default.

    ``effective_model_timeout`` (used for admin display) always resolves a
    concrete value; the resolver ModelClient actually calls returns ``None``
    absent an override so call sites omit the ``timeout`` kwarg entirely --
    see test_chat_call_passes_no_timeout_override_when_none_is_configured.
    """
    orchestrator = TaskOrchestrator(_seed(), client=ModelClient(timeout=64))
    orchestrator.set_model_timeout("gpt-example", 500)
    assert orchestrator.client.model_timeout_resolver("some-other-model") is None
    assert orchestrator.client.model_timeout_resolver("gpt-example") == 500.0
    assert orchestrator.effective_model_timeout("some-other-model") == 64.0


# -- HTTP API contract -------------------------------------------------------------


def _call(url: str, method: str, token: str, payload: dict | None = None) -> tuple[int, dict]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8") if payload is not None else None,
        headers={"content-type": "application/json", "authorization": f"Bearer {token}", "connection": "close"},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_http_model_timeout_view_set_clear_and_validation() -> None:
    orchestrator = TaskOrchestrator(_seed())
    server = build_server(orchestrator, port=0, security=SecurityConfig(auth_token=TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}/api/v1/model_timeouts"
    try:
        status, listing = _call(base, "GET", TOKEN)
        assert status == 200
        assert listing["items"] == [
            {
                "model": "gpt-example",
                "effective_timeout_seconds": 90.0,
                "override_timeout_seconds": None,
                "default_timeout_seconds": 90.0,
                "source": "default",
            }
        ]

        status, missing = _call(f"{base}/gpt-example", "DELETE", TOKEN)
        assert status == 404 and missing["error"]["code"] == "model_timeout_not_found"

        status, unknown_model = _call(f"{base}/no-such-model", "PATCH", TOKEN, {"timeout_seconds": 100})
        assert status == 404 and unknown_model["error"]["code"] == "model_timeout_not_found"

        status, bad_value = _call(f"{base}/gpt-example", "PATCH", TOKEN, {"timeout_seconds": -1})
        assert status == 400 and bad_value["error"]["code"] == "invalid_request"

        status, bad_fields = _call(f"{base}/gpt-example", "PATCH", TOKEN, {"timeout_seconds": 100, "surprise": 1})
        assert status == 400 and bad_fields["error"]["code"] == "unknown_fields"

        status, set_result = _call(f"{base}/gpt-example", "PATCH", TOKEN, {"timeout_seconds": 150})
        assert status == 200 and set_result["source"] == "override" and set_result["effective_timeout_seconds"] == 150.0

        status, detail = _call(f"{base}/gpt-example", "GET", TOKEN)
        assert status == 200 and detail["override_timeout_seconds"] == 150.0
        assert detail["audit_history"][0]["event_type"] == "model_timeout_set"

        status, cleared = _call(f"{base}/gpt-example", "DELETE", TOKEN)
        assert status == 200 and cleared["source"] == "default"

        status, missing_detail = _call(f"{base}/no-such-model", "GET", TOKEN)
        assert status == 404 and missing_detail["error"]["code"] == "model_timeout_not_found"
    finally:
        server.shutdown()


def test_http_model_timeouts_require_authentication() -> None:
    orchestrator = TaskOrchestrator(_seed())
    server = build_server(orchestrator, port=0, security=SecurityConfig(auth_token=TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}/api/v1/model_timeouts"
    try:
        status, body = _call(base, "GET", "wrong-token")
        assert status == 401
        status, body = _call(f"{base}/gpt-example", "PATCH", "wrong-token", {"timeout_seconds": 100})
        assert status == 401
    finally:
        server.shutdown()


# -- admin console UI surface -----------------------------------------------------


def test_admin_console_exposes_the_model_timeouts_panel() -> None:
    assert 'id="model-timeouts"' in ADMIN_HTML
    assert 'id="modelTimeoutRows"' in ADMIN_HTML
    assert 'apiFetch("/api/v1/model_timeouts")' in ADMIN_HTML
    assert 'method: "PATCH"' in ADMIN_HTML
    assert 'data-save-timeout' in ADMIN_HTML
    assert 'data-clear-timeout' in ADMIN_HTML
    for key in (
        "model_timeouts_title",
        "model_timeout_input_label",
        "save_model_timeout",
        "clear_model_timeout",
        "model_timeout_saved",
        "model_timeout_cleared",
        "no_model_timeouts",
    ):
        assert key in ADMIN_TRANSLATIONS["en"] and key in ADMIN_TRANSLATIONS["ko"]
    # No internal implementation terms leak into this operator-facing copy.
    customer_html = ADMIN_HTML.lower()
    assert "model_timeout_override" not in customer_html
    assert "orchestration_records" not in customer_html


if __name__ == "__main__":  # pragma: no cover
    import pytest as _pytest

    raise SystemExit(_pytest.main([__file__, "-q"]))
