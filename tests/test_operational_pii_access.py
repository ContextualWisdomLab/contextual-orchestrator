"""Operational PII stays visible; only secrets are destroyed in traces.

Buyers cannot complete incident follow-up when a requester email is replaced
with ``[REDACTED]``. NIST SP 800-53 Rev. 5 AC-6 / AU-2 and ISO/IEC 27001:2022
A.8.3 restrict *who* may read traces (bearer scope + audit). ISO/IEC 27001:2022
A.8.11 data masking applies to secrets (API keys, bearer tokens, passwords),
not to operational identifiers the authorized operator must act on.

ISO/IEC 29100 purpose specification: if the purpose of a trusted trace is
contacting the requester, irreversible email masking contradicts that purpose.
"""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator.orchestrator import (  # noqa: E402
    chat_completion_response,
    redact_text,
)


def test_redaction_keeps_requester_email_for_operator_follow_up() -> None:
    """A real support case: operator must email alice@example.com after a failed run."""
    text = "api_key='abcdefghijklmnopqrstuvwxyz' sent by alice@example.com"
    out = redact_text(text)
    assert "alice@example.com" in out
    assert "abcdefghijklmnopqrstuvwxyz" not in out
    assert "api_key='[REDACTED]'" in out


def test_redaction_still_masks_bearer_secrets() -> None:
    assert redact_text("Bearer abcdefghijklmnopqrstuvwxyz") == "Bearer [REDACTED]"


def test_trusted_trace_keeps_email_and_masks_secret() -> None:
    result = {
        "mode": "route",
        "answer": "ok",
        "trace": [
            {
                "agent_id": "general_agent",
                "output": "Contact alice@example.com; token=abcdefghijklmnopqrst",
            }
        ],
    }
    trace = chat_completion_response(result, include_trace=True)["orchestration"]["trace"]
    assert "alice@example.com" in trace[0]["output"]
    assert "abcdefghijklmnopqrst" not in trace[0]["output"]


if __name__ == "__main__":
    test_redaction_keeps_requester_email_for_operator_follow_up()
    test_redaction_still_masks_bearer_secrets()
    test_trusted_trace_keeps_email_and_masks_secret()
    print("ok")
