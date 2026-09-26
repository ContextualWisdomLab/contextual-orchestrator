"""Provider spend-limit exhaustion rules, one case per provider (ADR 0138)."""

from __future__ import annotations

import io
import json
import urllib.error

import pytest

from contextual_orchestrator.domain.provider_limits import (
    ProviderLimitAction,
    classify_provider_limit,
    limit_evidence_from_payload,
)
from contextual_orchestrator.provider_errors import classify_provider_failure

DROP = ProviderLimitAction.DROP_PROVIDER
NONE = ProviderLimitAction.NONE
TRANSIENT = ProviderLimitAction.TRANSIENT


def _classify(provider: str, status: int | None, body: dict) -> tuple[ProviderLimitAction, str]:
    signal = classify_provider_limit(provider, status, limit_evidence_from_payload(body))
    return signal.action, signal.reason


def test_openrouter_402_key_limit_drops() -> None:
    """OpenRouter 402 with an exhausted key limit drops the provider."""
    body = {"error": {"code": 402, "message": "Key limit", "metadata": {"limit_source": "openrouter_key_limit"}}}
    assert _classify("openrouter", 402, body) == (DROP, "openrouter_key_limit")


def test_openrouter_402_credits_drops() -> None:
    """OpenRouter 402 from exhausted account credits drops the provider."""
    body = {"error": {"code": 402, "metadata": {"limit_source": "openrouter_credits"}}}
    assert _classify("openrouter", 402, body) == (DROP, "openrouter_credits")


def test_openrouter_in_flight_budget_is_transient_not_a_drop() -> None:
    """The in-flight budget 402 clears when concurrent requests finish."""
    body = {"error": {"code": 402, "metadata": {"limit_source": "openrouter_in_flight_budget"}}}
    action, _ = _classify("openrouter", 402, body)
    assert action is TRANSIENT


def test_openrouter_plain_rate_limit_is_not_a_drop() -> None:
    """A 429 from OpenRouter is a rate limit, not exhaustion."""
    assert _classify("openrouter", 429, {"error": {"code": 429}})[0] is NONE


@pytest.mark.parametrize(
    "code",
    [
        "project_spend_limit_exceeded",
        "organization_spend_limit_exceeded",
        "credit_balance_exhausted",
        "insufficient_quota",
    ],
)
def test_openai_429_spend_limit_codes_drop(code: str) -> None:
    """OpenAI 429 with a spend-limit code drops the provider."""
    body = {"error": {"code": code, "type": "insufficient_quota", "message": "x"}}
    action, reason = _classify("openai", 429, body)
    assert action is DROP and reason == code


def test_openai_plain_rate_limit_429_is_not_a_drop() -> None:
    """``rate_limit_exceeded`` stays a retryable rate limit."""
    body = {"error": {"code": "rate_limit_exceeded", "type": "requests"}}
    assert _classify("openai", 429, body)[0] is NONE


@pytest.mark.parametrize("error_type", ["CreditsError", "MonthlyLimitError", "UserLimitError"])
def test_opencode_zen_401_balance_errors_drop(error_type: str) -> None:
    """OpenCode Zen reports exhausted balance as 401 with a typed error."""
    body = {"type": "error", "error": {"type": error_type, "message": "x"}}
    assert _classify("opencode_zen", 401, body) == (DROP, error_type)


def test_opencode_zen_bad_key_401_is_not_a_drop() -> None:
    """A bad key (``AuthError``) is a credential problem, not exhaustion."""
    body = {"type": "error", "error": {"type": "AuthError", "message": "Invalid API key."}}
    assert _classify("opencode_zen", 401, body)[0] is NONE


def test_opencode_go_usage_limit_429_drops() -> None:
    """OpenCode Go reports its usage limit as 429 ``GoUsageLimitError``."""
    body = {"type": "error", "error": {"type": "GoUsageLimitError", "message": "x"}}
    assert _classify("opencode_go", 429, body) == (DROP, "GoUsageLimitError")


def test_opencode_go_plain_rate_limit_is_not_a_drop() -> None:
    """Other Go 429s remain rate limits."""
    body = {"type": "error", "error": {"type": "RateLimitError"}}
    assert _classify("opencode_go", 429, body)[0] is NONE


def test_bytez_402_drops() -> None:
    """Bytez signals exhausted credits with HTTP 402."""
    body = {"error": "Payment Required", "status": 402}
    assert _classify("bytez", 402, body) == (DROP, "bytez_insufficient_credits")


def test_bytez_429_is_not_a_drop() -> None:
    """A Bytez concurrency 429 is not exhaustion."""
    assert _classify("bytez", 429, {"error": "Too many requests"})[0] is NONE


def test_experiential_insufficient_quota_429_drops() -> None:
    """Experiential Labs uses the OpenAI-style ``insufficient_quota`` 429."""
    body = {"error": {"code": "insufficient_quota", "type": "insufficient_quota"}}
    assert _classify("experiential_labs", 429, body) == (DROP, "insufficient_quota")


def test_experiential_plain_429_is_not_a_drop() -> None:
    """Experiential Labs rate limits stay rate limits."""
    assert _classify("experiential_labs", 429, {"error": {"code": "rate_limit_exceeded"}})[0] is NONE


def test_generic_402_drops_unknown_provider() -> None:
    """Payment Required from any provider means its balance cannot fund the call."""
    assert _classify("some_gateway", 402, {})[0] is DROP


def test_in_stream_error_uses_numeric_code_as_status() -> None:
    """An error event inside a 200 stream is classified from its ``error.code``."""
    chunk = {"error": {"code": 402, "message": "x", "metadata": {"limit_source": "openrouter_credits"}}}
    assert _classify("openrouter", None, chunk) == (DROP, "openrouter_credits")
    assert _classify("openrouter", 200, chunk) == (DROP, "openrouter_credits")
    zen_chunk = {"type": "error", "error": {"type": "CreditsError"}}
    assert _classify("opencode_zen", None, zen_chunk) == (DROP, "CreditsError")


def test_evidence_keeps_identifiers_and_drops_free_text() -> None:
    """Messages never enter limit evidence; long or spaced values are refused."""
    body = {"error": {"code": "insufficient_quota", "message": "secret prompt text", "type": "x" * 100}}
    evidence = limit_evidence_from_payload(body)
    assert evidence == {"error_code": "insufficient_quota"}
    assert limit_evidence_from_payload("not a mapping") == {}


def test_http_error_carries_limit_evidence_through_classification() -> None:
    """``classify_provider_failure`` attaches bounded evidence without changing detail."""
    payload = {"error": {"code": "project_spend_limit_exceeded", "message": "Over limit"}}
    exc = urllib.error.HTTPError(
        "https://api.openai.example/v1/chat/completions", 429, "Too Many Requests", {},
        io.BytesIO(json.dumps(payload).encode()),
    )
    error = classify_provider_failure(exc, agent_id="a", model="m")
    assert error.limit_evidence == {"error_code": "project_spend_limit_exceeded"}
    assert "limit_evidence" not in error.detail
    rewrapped = classify_provider_failure(error, agent_id="a", model="m", transport="stream")
    assert rewrapped.limit_evidence == error.limit_evidence
