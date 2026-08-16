"""Fuzz-seam honesty for omit-preferred max_tokens and boolean top_logprobs.

Locks ``exercise_output_token_budget`` so arbitrary SDK bodies cannot crash
the new resolver, and so invoice-lookup ``max_completion_tokens: null`` plus
``max_tokens=0`` still fails closed.
"""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import server  # noqa: E402
from contextual_orchestrator.server import RequestError  # noqa: E402
from fuzz.targets import exercise_output_token_budget, exercise_request_body  # noqa: E402


def test_exercise_output_token_budget_rejects_zero_legacy_when_preferred_is_omit() -> None:
    """Invoice-lookup SDKs send null preferred + max_tokens=0; must not bill."""
    try:
        server._resolve_chat_output_token_budget(
            {"max_completion_tokens": None, "max_tokens": 0}
        )
    except RequestError as exc:
        assert exc.status == 400
        assert exc.code == "invalid_max_tokens"
    else:
        raise AssertionError("omit preferred must still fail-closed on max_tokens=0")
    exercise_output_token_budget({"max_completion_tokens": None, "max_tokens": 0})


def test_exercise_output_token_budget_rejects_zero_legacy_when_preferred_is_blank() -> None:
    """Empty-string preferred is omit; sibling max_tokens=0 must still 400."""
    try:
        server._resolve_chat_output_token_budget(
            {"max_completion_tokens": "  ", "max_tokens": 0}
        )
    except RequestError as exc:
        assert exc.code == "invalid_max_tokens"
    else:
        raise AssertionError("blank preferred must still fail-closed on max_tokens=0")
    exercise_output_token_budget({"max_completion_tokens": "  ", "max_tokens": 0})


def test_exercise_output_token_budget_accepts_positive_legacy_when_preferred_is_omit() -> None:
    budget = exercise_output_token_budget(
        {"max_completion_tokens": None, "max_tokens": 16}
    )
    assert budget == 16


def test_exercise_output_token_budget_rejects_boolean_top_logprobs() -> None:
    """JSON false is a bool, not integer 0 — do not omit-as-zero and bill."""
    try:
        server._validate_completions_top_logprobs({"top_logprobs": False})
    except RequestError as exc:
        assert exc.status == 400
        assert exc.code == "invalid_top_logprobs"
    else:
        raise AssertionError("top_logprobs=false must be invalid_top_logprobs")
    exercise_output_token_budget({"top_logprobs": False})


def test_exercise_request_body_drives_output_token_budget() -> None:
    """Decoded request bodies must hit the resolver without an unhandled crash."""
    exercise_request_body(
        b'{"max_completion_tokens":null,"max_tokens":0,"top_logprobs":false}'
    )
    exercise_request_body(b'{"max_completion_tokens":null,"max_tokens":16}')
    exercise_request_body(b'{"top_logprobs":0}')


def test_exercise_output_token_budget_ignores_non_dict() -> None:
    assert exercise_output_token_budget("not-a-body") is None
    assert exercise_output_token_budget(None) is None
    assert exercise_output_token_budget([1, 2]) is None


if __name__ == "__main__":
    test_exercise_output_token_budget_rejects_zero_legacy_when_preferred_is_omit()
    test_exercise_output_token_budget_rejects_zero_legacy_when_preferred_is_blank()
    test_exercise_output_token_budget_accepts_positive_legacy_when_preferred_is_omit()
    test_exercise_output_token_budget_rejects_boolean_top_logprobs()
    test_exercise_request_body_drives_output_token_budget()
    test_exercise_output_token_budget_ignores_non_dict()
    print("ok")
