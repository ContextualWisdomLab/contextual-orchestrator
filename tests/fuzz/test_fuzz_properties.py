"""Property-based (Hypothesis) fuzz tests for untrusted-input surfaces.

These run in the normal ``pytest`` suite on every platform and Python version --
no native toolchain required -- and share the exact ``exercise_*`` invariant
checks used by the Atheris coverage-guided harnesses in ``fuzz/``. Hypothesis is
MPL-2.0 (permissive, no copyleft on your code).

The Atheris harnesses (``fuzz/fuzz_*.py``) provide coverage-guided fuzzing in CI;
this module provides fast, deterministic, always-on regression coverage of the
same invariants and shrinks any counterexample to a minimal repro.
"""

from __future__ import annotations

import json

from hypothesis import given, settings, strategies as st

from contextual_orchestrator import server
from contextual_orchestrator.server import RequestError
from fuzz.targets import (
    exercise_agent_config,
    exercise_orchestration,
    exercise_output_token_budget,
    exercise_redaction,
    exercise_request_body,
)

# Keep per-test wall time small so the suite stays cheap in CI.
_SETTINGS = settings(max_examples=200, deadline=None)

# JSON-ish values Hypothesis can build without recursion blowups.
_json_scalars = st.none() | st.booleans() | st.integers() | st.floats(allow_nan=False, allow_infinity=False) | st.text()
_json_values = st.recursive(
    _json_scalars,
    lambda children: st.lists(children, max_size=6) | st.dictionaries(st.text(max_size=12), children, max_size=6),
    max_leaves=25,
)


@_SETTINGS
@given(st.binary(max_size=4096))
def test_request_body_never_crashes_on_raw_bytes(raw: bytes) -> None:
    exercise_request_body(raw)


@_SETTINGS
@given(_json_values.map(lambda v: json.dumps(v).encode("utf-8")))
def test_request_body_never_crashes_on_valid_json(raw: bytes) -> None:
    exercise_request_body(raw)


@_SETTINGS
@given(
    st.fixed_dictionaries(
        {
            "run_mode": st.sampled_from(["auto", "route", "conduct", "bogus", "", 3, None]),
            "messages": st.lists(
                st.fixed_dictionaries(
                    {
                        "role": st.sampled_from(["user", "system", "assistant", "tool", "root", 1]),
                        "content": st.text() | st.integers() | st.none(),
                    }
                ),
                max_size=5,
            ),
            "extra_field": st.text(max_size=8),
        }
    ).map(lambda v: json.dumps(v).encode("utf-8"))
)
def test_request_body_validators_on_structured_input(raw: bytes) -> None:
    exercise_request_body(raw)


def test_request_body_rejects_unhashable_message_role() -> None:
    exercise_request_body(b'{"messages":[{"role":[],"":[],"modnt":""}]}')


def test_output_token_budget_rejects_zero_legacy_when_preferred_is_omit() -> None:
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


def test_output_token_budget_rejects_zero_legacy_when_preferred_is_blank() -> None:
    """Empty-string preferred is omit; sibling max_tokens=0 must still 400."""
    try:
        server._resolve_chat_output_token_budget(
            {"max_completion_tokens": "  ", "max_tokens": 0}
        )
    except RequestError as exc:
        assert exc.code == "invalid_max_tokens"
    else:
        raise AssertionError("blank preferred must still fail-closed on max_tokens=0")


def test_output_token_budget_accepts_positive_legacy_when_preferred_is_omit() -> None:
    budget = server._resolve_chat_output_token_budget(
        {"max_completion_tokens": None, "max_tokens": 16}
    )
    assert budget == 16
    assert (
        exercise_output_token_budget(
            {"max_completion_tokens": None, "max_tokens": 16}
        )
        == 16
    )


def test_output_token_budget_rejects_boolean_top_logprobs() -> None:
    """JSON false is a bool, not integer 0 — do not omit-as-zero and bill."""
    try:
        server._validate_completions_top_logprobs({"top_logprobs": False})
    except RequestError as exc:
        assert exc.status == 400
        assert exc.code == "invalid_top_logprobs"
    else:
        raise AssertionError("top_logprobs=false must be invalid_top_logprobs")
    exercise_output_token_budget({"top_logprobs": False})


@_SETTINGS
@given(_json_values)
def test_output_token_budget_never_crashes_on_decoded_json(value: object) -> None:
    exercise_output_token_budget(value)


@_SETTINGS
@given(_json_values)
def test_agent_config_parser(value: object) -> None:
    exercise_agent_config(value)


@_SETTINGS
@given(
    st.builds(
        dict,
        id=st.text(),
        model=st.text() | st.integers() | st.none(),
        base_url=st.text(),
        priority=st.integers() | st.text() | st.none(),
        tags=st.lists(st.text(), max_size=5) | st.none(),
        disabled=st.booleans() | st.integers(),
    )
)
def test_agent_config_parser_shaped(value: dict) -> None:
    exercise_agent_config(value)


@_SETTINGS
@given(st.text(max_size=4096))
def test_redaction_never_crashes_and_is_idempotent(text: str) -> None:
    exercise_redaction(text)


@settings(max_examples=100, deadline=None)
@given(
    st.text(max_size=2048),
    st.sampled_from(["auto", "route", "conduct", "unknown"]),
)
def test_orchestration_on_arbitrary_prompt(prompt: str, mode: str) -> None:
    exercise_orchestration(prompt, mode)
