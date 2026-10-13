"""Provider limit-exhaustion classification (drop just that provider for the run).

A provider that answers "your key/account/workspace has no budget left" will
keep answering that for the rest of a run, so retrying it or sending the next
step to it wastes attempts. This rule recognizes those documented responses
per provider and says what the orchestrator should do:

* :attr:`ProviderLimitAction.DROP_PROVIDER` - exclude this provider for the
  rest of the run and continue with the others (fail closed if none remain).
* :attr:`ProviderLimitAction.TRANSIENT` - a short-lived budget condition
  (e.g. OpenRouter's in-flight budget); keep the provider, honor Retry-After.
* :attr:`ProviderLimitAction.NONE` - not a limit exhaustion (ordinary rate
  limits, bad credentials, outages keep their existing handling).

Sources (checked 2026-09-26):

* OpenRouter - HTTP 402 with ``error.metadata.limit_source`` in
  ``openrouter_key_limit`` / ``openrouter_credits`` /
  ``openrouter_in_flight_budget`` (the last is transient).
  https://openrouter.ai/docs/api/reference/limits,
  https://openrouter.ai/docs/api/reference/errors-and-debugging
* OpenAI - HTTP 429 with ``error.code`` ``project_spend_limit_exceeded``,
  ``organization_spend_limit_exceeded``, ``credit_balance_exhausted`` or
  ``insufficient_quota``; other 429s are rate limits.
  https://developers.openai.com/api/docs/guides/spend-limits,
  https://developers.openai.com/api/docs/guides/error-codes
* OpenCode Zen / Go - HTTP 401 with ``error.type`` ``CreditsError`` /
  ``MonthlyLimitError`` / ``UserLimitError`` (a bad key is ``AuthError``, also
  401); Go subscription windows answer HTTP 429 ``GoUsageLimitError``. From
  the vendor's own console source (anomalyco/opencode @ 696f41bc,
  ``packages/console/app/src/routes/zen/util/handler.ts``); not in the
  public docs.
* Bytez - HTTP 402 "Insufficient credits".
  https://docs.bytez.com/model-api/docs/billing
* Experiential Labs - HTTP 429 ``insufficient_quota`` (key daily cap, budget,
  credits, or free-tier allowance). https://platform.experientiallabs.ai/llms.txt
* Any other provider - HTTP 402 Payment Required (RFC 9110 15.5.3) is treated
  as billing exhaustion.

Errors can also arrive inside a streamed HTTP 200 response as an SSE event
whose JSON carries an ``error`` object (OpenRouter documents this); callers pass
``http_status=None`` and the numeric ``error.code`` stands in for the status.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Any, Mapping

_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9_.:\-]{1,64}$")

OPENAI_SPEND_LIMIT_CODES = frozenset(
    {
        "project_spend_limit_exceeded",
        "organization_spend_limit_exceeded",
        "credit_balance_exhausted",
        "insufficient_quota",
    }
)
OPENROUTER_EXHAUSTED_LIMIT_SOURCES = frozenset({"openrouter_key_limit", "openrouter_credits"})
OPENROUTER_TRANSIENT_LIMIT_SOURCES = frozenset({"openrouter_in_flight_budget"})
OPENCODE_BALANCE_ERROR_TYPES = frozenset({"CreditsError", "MonthlyLimitError", "UserLimitError"})
OPENCODE_GO_LIMIT_ERROR_TYPE = "GoUsageLimitError"


class ProviderLimitAction(str, Enum):
    """What to do with a provider after one of its errors."""

    NONE = "none"
    DROP_PROVIDER = "drop_provider"
    TRANSIENT = "transient"


@dataclass(frozen=True)
class ProviderLimitSignal:
    """Classification result with a short machine-readable reason."""

    action: ProviderLimitAction
    reason: str = ""

    @property
    def drops_provider(self) -> bool:
        """Whether the provider must be excluded for the rest of the run."""
        return self.action is ProviderLimitAction.DROP_PROVIDER


NOT_A_LIMIT = ProviderLimitSignal(ProviderLimitAction.NONE)


def _safe(value: Any) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        value = str(value)
    if isinstance(value, str) and _SAFE_IDENTIFIER.match(value):
        return value
    return None


def limit_evidence_from_payload(payload: Any) -> dict[str, str]:
    """Extract bounded identifier fields a limit classifier needs from an error body.

    Only short identifier-like values are kept (no free-text messages), so the
    evidence is safe to attach to exceptions and logs. Recognized fields:
    ``error.code``, ``error.type``, ``error.metadata.limit_source``,
    ``error.metadata.reason``, top-level ``type``/``status``, and a top-level
    string ``error`` (Bytez uses ``{"status": 402, "error": "Payment Required"}``).
    """
    evidence: dict[str, str] = {}
    if not isinstance(payload, Mapping):
        return evidence
    error = payload.get("error")
    if isinstance(error, Mapping):
        for source, target in (("code", "error_code"), ("type", "error_type")):
            value = _safe(error.get(source))
            if value is not None:
                evidence[target] = value
        metadata = error.get("metadata")
        if isinstance(metadata, Mapping):
            for source in ("limit_source", "reason"):
                value = _safe(metadata.get(source))
                if value is not None:
                    evidence[source] = value
    elif isinstance(error, str):
        value = _safe(error.replace(" ", "_"))
        if value is not None:
            evidence["top_level_error"] = value
    for source, target in (("type", "top_level_type"), ("status", "top_level_status")):
        value = _safe(payload.get(source))
        if value is not None:
            evidence[target] = value
    return evidence


def _effective_status(http_status: int | None, evidence: Mapping[str, str]) -> int | None:
    if type(http_status) is int and http_status != 200:
        return http_status
    for key in ("error_code", "top_level_status"):
        raw = evidence.get(key, "")
        if raw.isdigit() and len(raw) == 3:
            return int(raw)
    return None


def classify_provider_limit(
    provider_name: str,
    http_status: int | None,
    evidence: Mapping[str, str] | None,
) -> ProviderLimitSignal:
    """Classify one provider error as limit exhaustion, transient budget, or neither.

    ``provider_name`` is the CO provider id (``ModelAgent.provider_name``),
    ``http_status`` the upstream status (``None`` or ``200`` for an in-stream
    error), and ``evidence`` the output of :func:`limit_evidence_from_payload`.
    """
    evidence = dict(evidence or {})
    status = _effective_status(http_status, evidence)
    error_code = evidence.get("error_code", "")
    error_type = evidence.get("error_type", "") or evidence.get("top_level_type", "")
    provider = (provider_name or "").strip().lower()

    if provider == "openrouter" and status == 402:
        source = evidence.get("limit_source", "")
        if (
            source in OPENROUTER_TRANSIENT_LIMIT_SOURCES
            or evidence.get("reason") == "in_flight_budget_exhausted"
        ):
            return ProviderLimitSignal(ProviderLimitAction.TRANSIENT, "openrouter_in_flight_budget")
        if source in OPENROUTER_EXHAUSTED_LIMIT_SOURCES:
            return ProviderLimitSignal(ProviderLimitAction.DROP_PROVIDER, source)
        return ProviderLimitSignal(ProviderLimitAction.DROP_PROVIDER, "openrouter_payment_required")

    if provider == "openai" and status == 429:
        codes = {error_code, error_type}
        matched = sorted(codes & OPENAI_SPEND_LIMIT_CODES)
        if matched:
            # Prefer the specific code over the generic insufficient_quota type.
            specific = [code for code in matched if code != "insufficient_quota"]
            return ProviderLimitSignal(
                ProviderLimitAction.DROP_PROVIDER, (specific or matched)[0]
            )
        return NOT_A_LIMIT

    if provider in {"opencode_zen", "opencode_go"}:
        if error_type in OPENCODE_BALANCE_ERROR_TYPES and status in (401, None):
            return ProviderLimitSignal(ProviderLimitAction.DROP_PROVIDER, error_type)
        if (
            provider == "opencode_go"
            and error_type == OPENCODE_GO_LIMIT_ERROR_TYPE
            and status in (429, None)
        ):
            return ProviderLimitSignal(ProviderLimitAction.DROP_PROVIDER, error_type)
        if status == 402:
            return ProviderLimitSignal(ProviderLimitAction.DROP_PROVIDER, "payment_required")
        return NOT_A_LIMIT

    if provider == "bytez" and status == 402:
        return ProviderLimitSignal(ProviderLimitAction.DROP_PROVIDER, "bytez_insufficient_credits")

    if provider == "experiential_labs":
        if status == 429 and "insufficient_quota" in {error_code, error_type}:
            return ProviderLimitSignal(ProviderLimitAction.DROP_PROVIDER, "insufficient_quota")
        if status == 402:
            return ProviderLimitSignal(ProviderLimitAction.DROP_PROVIDER, "payment_required")
        return NOT_A_LIMIT

    if status == 402:
        return ProviderLimitSignal(ProviderLimitAction.DROP_PROVIDER, "payment_required")
    return NOT_A_LIMIT


__all__ = [
    "NOT_A_LIMIT",
    "OPENAI_SPEND_LIMIT_CODES",
    "OPENCODE_BALANCE_ERROR_TYPES",
    "OPENCODE_GO_LIMIT_ERROR_TYPE",
    "OPENROUTER_EXHAUSTED_LIMIT_SOURCES",
    "OPENROUTER_TRANSIENT_LIMIT_SOURCES",
    "ProviderLimitAction",
    "ProviderLimitSignal",
    "classify_provider_limit",
    "limit_evidence_from_payload",
]
