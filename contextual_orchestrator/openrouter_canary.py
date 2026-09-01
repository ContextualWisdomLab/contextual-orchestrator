"""Bounded, opt-in evidence for one currently free OpenRouter model."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import tempfile
import time
from typing import Any, Callable

from .credentials import get_credential
from .model_discovery import (
    DiscoveredModel,
    PROVIDER_MODEL_SOURCES,
    _deduplicate_discovered_models,
    _requires_non_text_input,
    agent_from_discovered,
    discover_provider_models,
    is_discovered_chat_candidate,
)
from .orchestrator import ModelClient


class OpenRouterCanaryError(RuntimeError):
    """Raised before transport when the canary contract is incomplete."""


@dataclass(frozen=True)
class OpenRouterCanaryLimits:
    """Explicit operator caps for the optional live request."""

    max_requests: int
    max_output_tokens: int
    timeout_seconds: int
    retention_days: int

    def validate(self) -> None:
        """Reject absent, boolean, or non-positive cap values."""
        for name, value in asdict(self).items():
            if type(value) is not int or value < 1:
                raise OpenRouterCanaryError(f"{name} must be a positive integer")


def _eligible(models: list[DiscoveredModel]) -> list[DiscoveredModel]:
    """Return price-complete, text-chat OpenRouter rows in stable order."""
    return sorted(
        (
            model
            for model in models
            if model.provider_name == "openrouter"
            and model.prompt_price_per_1k == 0.0
            and model.completion_price_per_1k == 0.0
            and model.is_free is True
            and not model.unit_prices
            and model.currency_code == "USD"
            and not model.evidence_only
            and model.spend_admitted
            and is_discovered_chat_candidate(model)
            and not _requires_non_text_input(model)
        ),
        key=lambda model: model.model_id,
    )


def _write_evidence(path: Path, evidence: dict[str, Any]) -> None:
    """Atomically publish one secret- and prompt-free JSON evidence document."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(evidence, stream, sort_keys=True)
            stream.write("\n")
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def _prepare_evidence_path(path: Path, current_time: int) -> None:
    """Remove expired prior evidence and prove a secure atomic write is possible."""
    try:
        prior = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, UnicodeError, json.JSONDecodeError):
        prior = None
    if (
        isinstance(prior, dict)
        and prior.get("provider") == "openrouter"
        and type(prior.get("expires_at")) is int
        and prior["expires_at"] <= current_time
    ):
        path.unlink(missing_ok=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.preflight.", dir=path.parent
    )
    os.close(descriptor)
    os.unlink(temporary_name)
    if path.exists() and not path.is_file():
        raise OpenRouterCanaryError("evidence output must be a regular file path")


def run_openrouter_free_canary(
    *,
    live: bool,
    limits: OpenRouterCanaryLimits | None = None,
    evidence_output: Path | None = None,
    discover: Callable[..., list[DiscoveredModel]] = discover_provider_models,
    client_factory: Callable[..., ModelClient] = ModelClient,
    now: Callable[[], float] = time.time,
) -> dict[str, Any]:
    """Discover a current free candidate and optionally issue one bounded request."""
    source = next(
        item for item in PROVIDER_MODEL_SOURCES if item.provider_name == "openrouter"
    )
    if not get_credential(source.credential_name):
        raise OpenRouterCanaryError(
            "OPENROUTER_API_KEY is unavailable in the KV registry"
        )
    if live:
        if limits is None or evidence_output is None:
            raise OpenRouterCanaryError(
                "live mode requires all caps and an evidence output path"
            )
        limits.validate()
    discovered_at = int(now())
    if live:
        assert evidence_output is not None
        try:
            _prepare_evidence_path(evidence_output, discovered_at)
        except OSError as exc:
            raise OpenRouterCanaryError("evidence output is not writable") from exc
    candidates = _eligible(
        _deduplicate_discovered_models(
            discover(source, timeout=limits.timeout_seconds if limits else 10)
        )
    )
    if not candidates:
        raise OpenRouterCanaryError(
            "current discovery has no unambiguous zero-price chat candidate"
        )
    selected = candidates[0]
    evidence: dict[str, Any] = {
        "schema_version": 1,
        "mode": "live" if live else "dry_run",
        "provider": "openrouter",
        "model_id": selected.model_id,
        "discovered_at": discovered_at,
        "price_evidence": {
            "prompt_price_per_1k": 0.0,
            "completion_price_per_1k": 0.0,
            "currency_code": "USD",
        },
        "request_count": 0,
    }
    if live:
        assert limits is not None and evidence_output is not None
        client = client_factory(
            timeout=limits.timeout_seconds,
            max_output_tokens=limits.max_output_tokens,
            max_retries=0,
            temperature=0.0,
        )
        client.chat(
            agent_from_discovered(selected), [{"role": "user", "content": "Reply OK."}]
        )
        evidence.update(
            {
                "request_count": 1,
                "limits": asdict(limits),
                "expires_at": discovered_at + limits.retention_days * 86400,
                "outcome": "completed",
            }
        )
        _write_evidence(evidence_output, evidence)
    return evidence
