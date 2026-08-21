"""Tests for request session binding and prompt-safe telemetry."""

from contextual_orchestrator.telemetry import (
    current_session_id,
    reset_session_id,
    session_id_from_headers,
    session_id_from_metadata,
    set_session_id,
    traced,
)


def test_session_id_accepts_lineageweave_header_and_metadata():
    """The two compatible transport forms identify the same processing session."""
    assert (
        session_id_from_headers({"x-lineageweave-session-id": "session-1"})
        == "session-1"
    )
    assert (
        session_id_from_metadata({"lineageweave_post_session_id": "session-1"})
        == "session-1"
    )


def test_session_binding_is_reset():
    """A request cannot leak its session into a later request context."""
    token = set_session_id("session-2")
    try:
        assert current_session_id() == "session-2"
    finally:
        reset_session_id(token)
    assert current_session_id() is None


def test_traced_preserves_provider_error():
    """Tracing records failure but never changes the provider contract."""
    try:
        with traced("contextual_orchestrator.test.failure"):
            raise RuntimeError("provider failure")
    except RuntimeError as exc:
        assert str(exc) == "provider failure"
    else:  # pragma: no cover
        raise AssertionError("traced must preserve operation failures")
