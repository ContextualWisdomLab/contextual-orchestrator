"""Operational alert classification for gateway incident routing."""

from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any


_LITELLM_PATTERN = re.compile(r"\blitellm\b", re.IGNORECASE)
_PRISMA_PATTERN = re.compile(r"\bprisma\b", re.IGNORECASE)
_P2028_PATTERN = re.compile(r"(?i)(?:error_code[\"']?\s*[:=]\s*[\"']?)?P2028\b")
_TRANSACTION_START_PATTERN = re.compile(r"unable to start a transaction in the given time", re.IGNORECASE)
_NON_BLOCKING_PATTERN = re.compile(r"\[?non[- ]blocking\]?", re.IGNORECASE)
_SPEND_LOG_PATTERN = re.compile(r"update\s+spend\s+logs?|spend[-_ ]?logs?", re.IGNORECASE)
_DB_EXCEPTION_PATTERN = re.compile(r"db[_ -]?exceptions?|db read/write call failed", re.IGNORECASE)


_SUPPRESSED_ACTIONS = [
    "Drop from outage/page routing while recording a suppressed-alert audit event.",
    "Keep inference health, latency, and user-facing HTTP error-rate alerts active.",
    "Review LiteLLM, PgCat, and PostgreSQL pool budgets if suppressed counts trend upward.",
]

_ESCALATION_ACTIONS = [
    "Route to normal operator review or incident policy.",
    "Check inference health, request error rate, and customer-facing latency before downgrading.",
    "Only suppress after a specific non-blocking persistence signature is added and tested.",
]


def classify_operational_alert(alert: Mapping[str, Any]) -> dict[str, Any]:
    """Classify an external gateway alert before it becomes a page or outage.

    The classifier intentionally returns a derived decision, not the raw alert
    body. Alert payloads can contain URLs, headers, or request fragments, so the
    response keeps only signal names and operator actions.
    """
    text = _flatten_alert_text(alert)
    matched_signals = _matched_signals(text)
    is_litellm_p2028_spend_log = {
        "litellm_proxy",
        "prisma_client",
        "p2028_transaction_start_timeout",
        "transaction_start_timeout",
        "non_blocking_context",
        "spend_log_update",
    }.issubset(matched_signals)

    if is_litellm_p2028_spend_log:
        return {
            "classification_id": "litellm_prisma_p2028_spend_log_non_blocking",
            "source_component": "external_litellm_proxy",
            "classification_status": "suppressed",
            "incident_routing": "drop",
            "page_required": False,
            "service_impact": "none_observed",
            "normalized_severity": "info",
            "reason_code": "non_blocking_spend_log_transaction_timeout",
            "matched_signals": sorted(matched_signals),
            "rationale": (
                "LiteLLM marked the Prisma spend-log update as non-blocking; "
                "P2028 transaction-start pressure is a persistence backlog signal, "
                "not standalone proof that inference is unavailable."
            ),
            "operator_actions": list(_SUPPRESSED_ACTIONS),
            "audit_event_name": "operational_alert_suppressed",
        }

    return {
        "classification_id": "generic_gateway_alert_review",
        "source_component": "external_gateway",
        "classification_status": "escalate",
        "incident_routing": "normal_policy",
        "page_required": _page_required(alert, text),
        "service_impact": "unknown",
        "normalized_severity": _normalized_severity(alert, text),
        "reason_code": "no_suppression_signature_match",
        "matched_signals": sorted(matched_signals),
        "rationale": (
            "The alert did not match the complete non-blocking LiteLLM Prisma "
            "spend-log P2028 signature, so it must not be suppressed automatically."
        ),
        "operator_actions": list(_ESCALATION_ACTIONS),
        "audit_event_name": "operational_alert_escalated",
    }


def _matched_signals(text: str) -> set[str]:
    signals: set[str] = set()
    if _LITELLM_PATTERN.search(text):
        signals.add("litellm_proxy")
    if _PRISMA_PATTERN.search(text):
        signals.add("prisma_client")
    if _P2028_PATTERN.search(text):
        signals.add("p2028_transaction_start_timeout")
    if _TRANSACTION_START_PATTERN.search(text):
        signals.add("transaction_start_timeout")
    if _NON_BLOCKING_PATTERN.search(text):
        signals.add("non_blocking_context")
    if _SPEND_LOG_PATTERN.search(text):
        signals.add("spend_log_update")
    if _DB_EXCEPTION_PATTERN.search(text):
        signals.add("db_exception_alert")
    return signals


def _flatten_alert_text(value: Any) -> str:
    if isinstance(value, Mapping):
        parts: list[str] = []
        for key, child in value.items():
            parts.append(str(key))
            parts.append(_flatten_alert_text(child))
        return "\n".join(parts)
    if isinstance(value, list | tuple | set):
        return "\n".join(_flatten_alert_text(item) for item in value)
    if value is None:
        return ""
    return str(value)


def _normalized_severity(alert: Mapping[str, Any], text: str) -> str:
    level = str(alert.get("level") or alert.get("severity") or "").strip().lower()
    if not level:
        match = re.search(r"(?im)^\s*(level|severity)\s*:\s*([a-z]+)\s*$", text)
        level = match.group(2).lower() if match else ""
    if level in {"critical", "fatal"}:
        return "critical"
    if level in {"high", "error"}:
        return "high"
    if level in {"medium", "warning", "warn"}:
        return "warning"
    if level in {"low", "info", "informational"}:
        return "info"
    return "unknown"


def _page_required(alert: Mapping[str, Any], text: str) -> bool:
    return _normalized_severity(alert, text) in {"critical", "high"}
