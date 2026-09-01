"""Bounded, opt-in evidence for one currently free OpenRouter model."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import stat
import tempfile
import time
from typing import Any, Callable, Iterator

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
from .nim_evidence import NimEvidenceError, _publication_lock
from .orchestrator import ModelClient


class OpenRouterCanaryError(RuntimeError):
    """Raised before transport when the canary contract is incomplete."""

    code = "openrouter_canary_failed"


@contextmanager
def _evidence_lock(path: Path) -> Iterator[None]:
    """Serialize operations for one evidence path using the shared safe lock."""
    try:
        with _publication_lock(path):
            yield
    except NimEvidenceError as exc:
        raise OpenRouterCanaryError("canary evidence lock is unavailable") from exc


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
            and type(model.prompt_price_per_1k) is float
            and model.prompt_price_per_1k == 0.0
            and type(model.completion_price_per_1k) is float
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


def _is_live_canary_evidence(document: object) -> bool:
    """Return whether a document carries this canary's deletion identity."""
    return (
        isinstance(document, dict)
        and document.get("schema_version") == 1
        and document.get("provider") == "openrouter"
        and document.get("mode") == "live"
    )


def _prepare_evidence_path(path: Path, current_time: int) -> None:
    """Remove expired prior evidence and prove a secure atomic write is possible."""
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        mode = None
    if mode is not None and not stat.S_ISREG(mode):
        raise OpenRouterCanaryError("evidence output must be a regular file path")
    if mode is not None:
        try:
            prior = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise OpenRouterCanaryError("existing evidence could not be inspected") from exc
        if not _is_live_canary_evidence(prior):
            raise OpenRouterCanaryError("evidence output contains unrelated data")
        expires_at = prior.get("expires_at")
        if type(expires_at) is not int:
            raise OpenRouterCanaryError("existing canary evidence has no valid expiry")
        if expires_at > current_time:
            raise OpenRouterCanaryError("unexpired canary evidence already exists")
        path.unlink()
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.preflight.", dir=path.parent
    )
    os.close(descriptor)
    os.unlink(temporary_name)


def prune_expired_openrouter_canary_evidence(
    path: Path, *, now: Callable[[], float] = time.time
) -> bool:
    """Remove one expired evidence file without contacting a provider."""
    with _evidence_lock(path):
        return _prune_expired_openrouter_canary_evidence(path, now=now)


def _prune_expired_openrouter_canary_evidence(
    path: Path, *, now: Callable[[], float]
) -> bool:
    """Inspect and remove one expired evidence file while its path is locked."""
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return False
    if not stat.S_ISREG(mode):
        raise OpenRouterCanaryError("canary evidence must be a regular file")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise OpenRouterCanaryError("canary evidence could not be inspected") from exc
    if not _is_live_canary_evidence(document):
        raise OpenRouterCanaryError("file is not OpenRouter canary evidence")
    expires_at = document.get("expires_at") if isinstance(document, dict) else None
    if type(expires_at) is not int:
        raise OpenRouterCanaryError("canary evidence has no valid expiry")
    if int(now()) < expires_at:
        return False
    try:
        path.unlink()
    except FileNotFoundError:
        return False
    return True


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
        assert evidence_output is not None
        with _evidence_lock(evidence_output):
            return _run_openrouter_free_canary_locked(
                live=live,
                source=source,
                limits=limits,
                evidence_output=evidence_output,
                discover=discover,
                client_factory=client_factory,
                now=now,
            )
    return _run_openrouter_free_canary_locked(
        live=live,
        source=source,
        limits=limits,
        evidence_output=evidence_output,
        discover=discover,
        client_factory=client_factory,
        now=now,
    )


def _run_openrouter_free_canary_locked(
    *,
    live: bool,
    source: Any,
    limits: OpenRouterCanaryLimits | None,
    evidence_output: Path | None,
    discover: Callable[..., list[DiscoveredModel]],
    client_factory: Callable[..., ModelClient],
    now: Callable[[], float],
) -> dict[str, Any]:
    """Run discovery and optional transport under the live evidence-path lock."""
    if live:
        assert evidence_output is not None
        try:
            _prepare_evidence_path(evidence_output, int(now()))
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
    discovered_at = int(now())
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
        evidence.update(
            {
                "request_count": 1,
                "limits": asdict(limits),
                "expires_at": discovered_at + limits.retention_days * 86400,
                "outcome": "pending",
            }
        )
        _write_evidence(evidence_output, evidence)
        client = client_factory(
            timeout=limits.timeout_seconds,
            max_output_tokens=limits.max_output_tokens,
            max_retries=0,
            temperature=0.0,
        )
        try:
            response = client.chat(
                agent_from_discovered(selected),
                [{"role": "user", "content": "Reply OK."}],
            )
        except Exception as exc:
            evidence["outcome"] = "failed"
            _write_evidence(evidence_output, evidence)
            raise OpenRouterCanaryError("OpenRouter canary request failed") from exc
        if not isinstance(response, str) or response.strip() != "OK":
            evidence["outcome"] = "invalid_response"
            _write_evidence(evidence_output, evidence)
            raise OpenRouterCanaryError("OpenRouter canary returned an invalid response")
        evidence["outcome"] = "completed"
        _write_evidence(evidence_output, evidence)
    return evidence
