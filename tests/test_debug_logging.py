"""Stdlib-only logging configuration: level parsing, lazy DEBUG emission, redaction safety net."""

from __future__ import annotations

import io
import json
import logging
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator.debug_logging import (  # noqa: E402
    DEFAULT_LOG_LEVEL_NAME,
    LOG_LEVEL_NAMES,
    configure_logging,
    log_debug_event,
    parse_log_level_name,
    response_metadata_for_log,
    summarize_payload_for_log,
    summarize_request_for_log,
)
from contextual_orchestrator.orchestrator import redact_text  # noqa: E402


@contextmanager
def _restored_root_logger() -> Iterator[None]:
    """Snapshot/restore root logger level+handlers so a test cannot leak global state."""
    root = logging.getLogger()
    original_level = root.level
    original_handlers = list(root.handlers)
    try:
        yield
    finally:
        for handler in list(root.handlers):
            if handler not in original_handlers:
                root.removeHandler(handler)
                handler.close()
        root.handlers = original_handlers
        root.setLevel(original_level)


def test_parse_log_level_name_accepts_known_levels_case_insensitively() -> None:
    assert parse_log_level_name("debug") == "DEBUG"
    assert parse_log_level_name("Warning") == "WARNING"
    assert parse_log_level_name("  ERROR  ") == "ERROR"
    assert parse_log_level_name("critical") == "CRITICAL"
    assert parse_log_level_name("info") == "INFO"


def test_parse_log_level_name_rejects_unknown_level() -> None:
    try:
        parse_log_level_name("VERBOSE")
    except ValueError as exc:
        assert "VERBOSE" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("an unknown level name must raise ValueError")


def test_default_log_level_name_is_warning_and_listed() -> None:
    assert DEFAULT_LOG_LEVEL_NAME == "WARNING"
    assert DEFAULT_LOG_LEVEL_NAME in LOG_LEVEL_NAMES
    assert LOG_LEVEL_NAMES == ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


def test_configure_logging_force_reapplies_level_across_calls() -> None:
    """Guards the classic basicConfig-is-a-no-op-after-first-call footgun."""
    with _restored_root_logger():
        configure_logging("DEBUG")
        assert logging.getLogger().getEffectiveLevel() == logging.DEBUG
        configure_logging("WARNING")
        assert logging.getLogger().getEffectiveLevel() == logging.WARNING
        configure_logging("ERROR")
        assert logging.getLogger().getEffectiveLevel() == logging.ERROR


def test_configure_logging_rejects_invalid_level_without_side_effects() -> None:
    with _restored_root_logger():
        configure_logging("INFO")
        try:
            configure_logging("NOT_A_LEVEL")
        except ValueError:
            pass
        else:  # pragma: no cover
            raise AssertionError("invalid level must raise, never silently configure")
        assert logging.getLogger().getEffectiveLevel() == logging.INFO


def test_configure_logging_without_redactor_attaches_no_filter() -> None:
    with _restored_root_logger():
        configure_logging("DEBUG")
        for handler in logging.getLogger().handlers:
            assert handler.filters == []


class _CountingRepr:
    """Sentinel whose ``__repr__`` counts calls, to prove lazy %-formatting."""

    def __init__(self) -> None:
        self.calls = 0

    def __repr__(self) -> str:  # pragma: no cover - executed only if formatting happens
        self.calls += 1
        return "<sentinel>"


def test_log_debug_event_skips_formatting_below_debug_level() -> None:
    logger = logging.getLogger("contextual_orchestrator.test.lazy")
    logger.setLevel(logging.WARNING)
    sentinel = _CountingRepr()
    log_debug_event(logger, "value=%r", sentinel)
    assert sentinel.calls == 0


def test_log_debug_event_formats_and_emits_when_debug_enabled() -> None:
    logger = logging.getLogger("contextual_orchestrator.test.lazy_enabled")
    logger.setLevel(logging.DEBUG)
    buffer = io.StringIO()
    handler = logging.StreamHandler(buffer)
    logger.addHandler(handler)
    logger.propagate = False
    try:
        sentinel = _CountingRepr()
        log_debug_event(logger, "value=%r", sentinel)
        assert sentinel.calls == 1
        assert "<sentinel>" in buffer.getvalue()
    finally:
        logger.removeHandler(handler)
        handler.close()


def test_configure_logging_redactor_masks_secret_shaped_content_in_captured_output() -> None:
    """THE key secret-leak test: a fake credential shape must never reach captured output."""
    fake_secret = "sk-FAKEFAKEFAKEFAKEFAKE1234567890"  # noqa: S105 - obviously non-functional fixture
    captured = io.StringIO()
    original_stderr = sys.stderr
    sys.stderr = captured
    try:
        with _restored_root_logger():
            configure_logging("DEBUG", redactor=redact_text)
            # codeql[py/clear-text-logging-sensitive-data] Intentional positive-control
            # fixture: `fake_secret` (defined above, already `# noqa: S105`'d) is a
            # hardcoded, non-functional literal, and this test's entire purpose is
            # proving `configure_logging(..., redactor=redact_text)` masks exactly this
            # shape before it reaches captured output -- see the assertions below and the
            # paired negative control immediately after this test.
            logging.getLogger("contextual_orchestrator.test.leak").debug(
                "provider payload leaked: %s", json.dumps({"api_key": fake_secret})
            )
    finally:
        sys.stderr = original_stderr
    output = captured.getvalue()
    assert "[REDACTED]" in output
    assert fake_secret not in output


def test_configure_logging_redactor_none_still_leaves_secret_unmasked() -> None:
    """Negative control: without a redactor, the same fake secret DOES leak.

    Proves the previous test is a real assertion, not a tautology -- it can
    fail (and, run this way, does) before the redactor is wired in.
    """
    fake_secret = "sk-FAKEFAKEFAKEFAKEFAKE1234567890"  # noqa: S105 - obviously non-functional fixture
    captured = io.StringIO()
    original_stderr = sys.stderr
    sys.stderr = captured
    try:
        with _restored_root_logger():
            configure_logging("DEBUG")  # no redactor at all
            # codeql[py/clear-text-logging-sensitive-data] Intentional negative-control
            # fixture: `fake_secret` (defined above, already `# noqa: S105`'d) is a
            # hardcoded, non-functional literal. This test deliberately logs it with NO
            # redactor to prove the positive-control test above is a real assertion (it
            # can fail before the redactor is wired in) rather than a tautology -- the
            # leak this line demonstrates is the exact property both tests exist to prove.
            logging.getLogger("contextual_orchestrator.test.leak_control").debug(
                "provider payload leaked: %s", json.dumps({"api_key": fake_secret})
            )
    finally:
        sys.stderr = original_stderr
    assert fake_secret in captured.getvalue()


def test_configure_logging_redactor_masks_exception_traceback_in_captured_output() -> None:
    """Exception tracebacks (`exc_info=True` / `logger.exception`) must be redacted too.

    `_RedactingLogFilter` previously only rewrote `record.msg`/`record.args`
    -- `record.exc_info` (and any already-rendered `record.exc_text`) passed
    through untouched. `logging.Formatter.format()` renders the traceback
    from `exc_info` *after* filters have already run and returned, so a call
    site using `exc_info=True` or `logger.exception(...)` could still leak a
    secret embedded in the exception's own `str()` straight into the
    formatted traceback, bypassing this safety net entirely -- exactly the
    kind of secret-shaped content (e.g. `api_key=sk-...`) this whole
    redaction system exists to catch.
    """
    fake_secret = "sk-FAKEFAKEFAKEFAKEFAKE1234567890"  # noqa: S105 - obviously non-functional fixture
    captured = io.StringIO()
    original_stderr = sys.stderr
    sys.stderr = captured
    try:
        with _restored_root_logger():
            configure_logging("DEBUG", redactor=redact_text)
            logger = logging.getLogger("contextual_orchestrator.test.leak_traceback")
            try:
                raise RuntimeError(f"upstream rejected request: api_key={fake_secret}")
            except RuntimeError:
                logger.exception("provider call failed")
    finally:
        sys.stderr = original_stderr
    output = captured.getvalue()
    assert "[REDACTED]" in output
    assert fake_secret not in output


def test_summarize_request_for_log_is_body_free_and_bounded() -> None:
    line = summarize_request_for_log(
        method="POST",
        path="/v1/chat/completions",
        status=200,
        latency_ms=12.345,
        session_id_hash="abc123",
    )
    assert "POST" in line
    assert "/v1/chat/completions" in line
    assert "200" in line
    assert "12.3" in line
    assert "abc123" in line


def test_summarize_request_for_log_handles_missing_status_and_session() -> None:
    line = summarize_request_for_log(method="GET", path="/healthz", status=None, latency_ms=0.5)
    assert "status=-" in line
    assert "session_id_hash=-" in line


def test_summarize_request_for_log_strips_query_string() -> None:
    """A query string on `path` is never logged, only the bare path before `?`.

    Deterministic unit-level counterpart to
    tests/test_telemetry.py::test_per_request_info_summary_never_includes_query_string,
    which exercises the same property end to end through a real server but
    can occasionally flake on unrelated threaded-server teardown timing; this
    test proves the property directly against the formatter with no
    threading involved.
    """
    fake_token = "sk-FAKEFAKEFAKEFAKEFAKEQUERYSTRING123"
    line = summarize_request_for_log(
        method="GET",
        path=f"/healthz?api_key={fake_token}",
        status=200,
        latency_ms=0.5,
    )
    assert "path=/healthz" in line
    assert "?" not in line
    assert fake_token not in line


def test_summarize_payload_for_log_truncates_and_labels() -> None:
    payload = {"choices": [{"message": {"content": "x" * 2000}}]}
    line = summarize_payload_for_log("response", payload, max_characters=100)
    assert line.startswith("response_summary ")
    assert len(line) < 200
    assert "...<truncated>" in line


def test_summarize_payload_for_log_handles_unserializable_payload() -> None:
    circular: dict[str, object] = {}
    circular["self"] = circular
    line = summarize_payload_for_log("request", circular)
    assert line.startswith("request_summary ")


def test_response_metadata_for_log_keeps_only_allowlisted_usage_counters() -> None:
    """CodeRabbit regression: a numeric-looking key must still be allowlisted by name.

    Before this fix, `response_metadata_for_log`'s "usage" summary kept ANY
    string key with a numeric value, not a fixed allowlist of known counter
    names. A provider's `usage` object is upstream-controlled JSON, so a key
    shaped like `"customer_note=<secret>"` with a throwaway numeric value
    would sail through the old numeric-only filter and get logged verbatim
    (CWE-532). This proves such a key is excluded while the real,
    allowlisted OpenAI-compatible counters still come through untouched.
    """
    fake_secret = "sk-FAKEFAKEFAKEFAKEFAKE1234567890"  # noqa: S105 - obviously non-functional fixture
    payload = {
        "model": "gpt-test",
        "choices": [{"message": {"content": "ok"}}],
        "usage": {
            "prompt_tokens": 12,
            "completion_tokens": 34,
            "total_tokens": 46,
            f"customer_note={fake_secret}": 1,
        },
    }

    metadata = response_metadata_for_log(payload)

    assert metadata["usage"] == {
        "prompt_tokens": 12,
        "completion_tokens": 34,
        "total_tokens": 46,
    }
    assert not any(fake_secret in str(key) for key in metadata["usage"])


def test_response_metadata_for_log_usage_none_when_no_allowlisted_keys_present() -> None:
    """An entirely non-allowlisted "usage" dict summarizes to an empty, not absent, dict.

    (`usage` stays a dict -- just with nothing left in it -- distinct from
    a payload with no "usage" key at all, which stays `None`.)
    """
    metadata = response_metadata_for_log(
        {"usage": {"unexpected_field": 1, "another_one": 2.5}}
    )
    assert metadata["usage"] == {}


if __name__ == "__main__":  # pragma: no cover
    test_parse_log_level_name_accepts_known_levels_case_insensitively()
    test_parse_log_level_name_rejects_unknown_level()
    test_default_log_level_name_is_warning_and_listed()
    test_configure_logging_force_reapplies_level_across_calls()
    test_configure_logging_rejects_invalid_level_without_side_effects()
    test_configure_logging_without_redactor_attaches_no_filter()
    test_log_debug_event_skips_formatting_below_debug_level()
    test_log_debug_event_formats_and_emits_when_debug_enabled()
    test_configure_logging_redactor_masks_secret_shaped_content_in_captured_output()
    test_configure_logging_redactor_none_still_leaves_secret_unmasked()
    test_summarize_request_for_log_is_body_free_and_bounded()
    test_summarize_request_for_log_handles_missing_status_and_session()
    test_summarize_payload_for_log_truncates_and_labels()
    test_summarize_payload_for_log_handles_unserializable_payload()
    test_response_metadata_for_log_keeps_only_allowlisted_usage_counters()
    test_response_metadata_for_log_usage_none_when_no_allowlisted_keys_present()
    print("ok")
