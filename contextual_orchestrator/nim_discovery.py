"""Evidence-grade NVIDIA NIM model discovery for agent-pool population.

Discovers OpenAI-compatible model IDs from a NIM-compatible ``/models`` endpoint
using the KV credential ``NVIDIA_NIM_API_KEY`` (never ``COPILOT_GITHUB_TOKEN``).
Operators convert discovered models into agent pool entries; routing still uses
the deterministic route/conduct policies grounded in Fugu / Conductor / TRINITY
paper contracts.

References
----------
Touvron, H., et al. (2023). *Llama 2: Open foundation and fine-tuned chat models*
(arXiv:2307.09288) — open weights commonly hosted on NIM for gateway evaluation.

Live discovery is optional: tests use offline fixtures so CI stays hermetic.
"""

from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlparse

from .credentials import get_credential

DEFAULT_NIM_MODELS_URL = "https://integrate.api.nvidia.com/v1/models"
NIM_CREDENTIAL_NAME = "NVIDIA_NIM_API_KEY"
# Bound catalog body consumption so a pathological allowlisted response cannot OOM the CLI.
NIM_CATALOG_MAX_BYTES = 8 * 1024 * 1024
# Hosts that may receive the NVIDIA_NIM_API_KEY on authenticated catalog requests.
ALLOWED_NIM_MODELS_HOSTS = frozenset(
    {
        "integrate.api.nvidia.com",
        "api.nvcf.nvidia.com",
    }
)


class NimDiscoveryError(ValueError):
    """Raised when NIM discovery cannot safely proceed (bad URL, etc.)."""


def validate_nim_models_url(models_url: str) -> str:
    """Return a normalized models catalog URL or raise ``NimDiscoveryError``.

    Authenticated requests only go to allowlisted NVIDIA HTTPS hosts with
    path ``/v1/models`` (optional trailing slash). No user-controlled host
    may receive ``NVIDIA_NIM_API_KEY``.
    """
    if not isinstance(models_url, str) or not models_url.strip():
        raise NimDiscoveryError("models_url must be a non-empty string")
    parsed = urlparse(models_url.strip())
    if parsed.scheme != "https":
        raise NimDiscoveryError("models_url must use https")
    if parsed.username or parsed.password:
        raise NimDiscoveryError("models_url must not embed credentials")
    if parsed.port not in (None, 443):
        raise NimDiscoveryError("models_url must use the default HTTPS port")
    hostname = (parsed.hostname or "").lower()
    if hostname not in ALLOWED_NIM_MODELS_HOSTS:
        raise NimDiscoveryError(
            f"models_url host {hostname!r} is not an allowlisted NVIDIA catalog host"
        )
    path = parsed.path.rstrip("/") or ""
    if path != "/v1/models":
        raise NimDiscoveryError("models_url path must be /v1/models")
    if parsed.query or parsed.fragment:
        raise NimDiscoveryError("models_url must not include query or fragment")
    return f"https://{hostname}/v1/models"


def discover_nim_models(
    *,
    models_url: str = DEFAULT_NIM_MODELS_URL,
    credential_name: str = NIM_CREDENTIAL_NAME,
    timeout_seconds: float = 30.0,
    transport: Any | None = None,
) -> dict[str, Any]:
    """Discover model IDs from a NIM-compatible OpenAI ``/models`` list endpoint.

    Parameters
    ----------
    models_url:
        Absolute HTTPS URL of the models listing endpoint. Must pass
        :func:`validate_nim_models_url` before any credential is attached.
    credential_name:
        KV credential name. Defaults to ``NVIDIA_NIM_API_KEY``.
    timeout_seconds:
        Socket timeout for the listing request.
    transport:
        Optional callable ``(request, timeout) -> bytes`` for tests. When set,
        ``measurement_status`` is ``offline_fixture`` (not live catalog).

    Returns
    -------
    dict
        ``measurement_status`` (``live_nim_catalog`` | ``offline_fixture`` |
        ``credential_missing``), ``model_ids`` (sorted unique strings), and
        ``source_url``. Never includes the raw API key.
    """
    safe_url = validate_nim_models_url(models_url)
    api_key = get_credential(credential_name)
    if not api_key:
        return {
            "measurement_status": "credential_missing",
            "model_ids": [],
            "source_url": safe_url,
            "credential_name": credential_name,
        }

    request = urllib.request.Request(  # nosemgrep -- dynamic-urllib-use: URL validated by validate_nim_models_url allowlist before auth header is attached.
        safe_url,
        headers={
            "authorization": f"Bearer {api_key}",
            "accept": "application/json",
        },
        method="GET",
    )

    if transport is not None:
        raw = transport(request, timeout_seconds)
        status = "offline_fixture"
    else:
        context = ssl.create_default_context()
        with urllib.request.urlopen(  # nosec B310 - URL validated by validate_nim_models_url (HTTPS allowlist).  # nosemgrep -- dynamic-urllib-use: URL validated by validate_nim_models_url allowlist before auth header is attached.
            request, timeout=timeout_seconds, context=context
        ) as response:
            content_length = response.headers.get("Content-Length")
            if content_length is not None:
                try:
                    declared = int(content_length)
                except ValueError as exc:
                    raise NimDiscoveryError("catalog Content-Length is not an integer") from exc
                if declared < 0 or declared > NIM_CATALOG_MAX_BYTES:
                    raise NimDiscoveryError(
                        f"catalog Content-Length {declared} exceeds bound {NIM_CATALOG_MAX_BYTES}"
                    )
            raw = response.read(NIM_CATALOG_MAX_BYTES + 1)
        status = "live_nim_catalog"

    if not isinstance(raw, (bytes, bytearray)):
        raise NimDiscoveryError("catalog transport must return bytes")
    if len(raw) > NIM_CATALOG_MAX_BYTES:
        raise NimDiscoveryError(
            f"catalog response exceeds bound of {NIM_CATALOG_MAX_BYTES} bytes"
        )

    payload = json.loads(raw.decode("utf-8"))
    model_ids = _extract_model_ids(payload)
    return {
        "measurement_status": status,
        "model_ids": model_ids,
        "source_url": safe_url,
        "model_count": len(model_ids),
    }


def models_to_agent_pool_entries(
    model_ids: list[str],
    *,
    base_url: str = "https://integrate.api.nvidia.com/v1",
    credential_key: str = NIM_CREDENTIAL_NAME,
    tags: tuple[str, ...] = ("reasoning", "writing"),
) -> list[dict[str, Any]]:
    """Map discovered model IDs to agent-pool JSON dicts (multi-word snake_case ids).

    Each model becomes one agent with a unique deterministic ``id``. Colliding
    slugs (normalization or 48-char truncation) get a stable numeric suffix.
    After ``model_group`` race lands on main (issue #102 / PR #114), operators
    may add ``model_group`` keys for replica race.
    """
    entries: list[dict[str, Any]] = []
    used_ids: set[str] = set()
    for index, model_id in enumerate(model_ids):
        agent_id = _unique_agent_id(model_id, used_ids)
        used_ids.add(agent_id)
        entries.append(
            {
                "id": agent_id,
                "model": model_id,
                "base_url": base_url,
                "credential_key": credential_key,
                "tags": list(tags),
                "priority": max(0, 10 - index),
            }
        )
    return entries


def _unique_agent_id(model_id: str, used_ids: set[str]) -> str:
    """Build ``nim_<slug>_agent`` and append ``_N`` when the id already exists."""
    slug = _slug_model_id(model_id)
    base = f"nim_{slug}_agent"
    if base not in used_ids:
        return base
    suffix = 2
    while True:
        candidate = f"{base}_{suffix}"
        if candidate not in used_ids:
            return candidate
        suffix += 1


def _extract_model_ids(payload: Any) -> list[str]:
    """Parse OpenAI-style ``{data: [{id: ...}]}`` or a bare list of ids/objects."""
    ids: list[str] = []
    if isinstance(payload, dict):
        data = payload.get("data", payload.get("models", []))
    else:
        data = payload
    if not isinstance(data, list):
        return []
    for item in data:
        if isinstance(item, str) and item.strip():
            ids.append(item.strip())
        elif isinstance(item, dict):
            mid = item.get("id") or item.get("model")
            if isinstance(mid, str) and mid.strip():
                ids.append(mid.strip())
    return sorted(set(ids))


def _slug_model_id(model_id: str) -> str:
    """Convert a provider model id into a multi-word-friendly snake_case token."""
    cleaned = []
    for char in model_id.lower():
        if char.isalnum():
            cleaned.append(char)
        else:
            cleaned.append("_")
    slug = "".join(cleaned).strip("_")
    while "__" in slug:
        slug = slug.replace("__", "_")
    if not slug:
        slug = "unnamed_model"
    # require_object_name needs two semantic words — ensure underscore present
    if "_" not in slug:
        slug = f"{slug}_model"
    return slug[:48]


# Capability labels used in offline inventory / dry-run benchmark plans (issue #86).
CAPABILITY_CHAT = "chat"
CAPABILITY_EMBEDDINGS = "embeddings"
CAPABILITY_IMAGE = "image"
CAPABILITY_AUDIO = "audio"
CAPABILITY_VIDEO = "video"
CAPABILITY_UNSUPPORTED = "unsupported"
CAPABILITY_UNKNOWN = "unknown"

_BENCHMARK_POLICY_NAMES = (
    "direct_worker",
    "route_once",
    "bounded_conduct",
    "hindsight_best_single",
)


def classify_model_capability_hint(model_id: str) -> str:
    """Return a coarse capability label from the model id string alone (offline).

    This is a catalog hint for dry-run inventory, not a live probe. Live
    capability probing (issue #86) must opt in with ``RUN_LIVE_NIM_TESTS=1`` and
    never invent success for unsupported modalities.
    """
    if not isinstance(model_id, str) or not model_id.strip():
        return CAPABILITY_UNSUPPORTED
    token = model_id.lower()
    if any(part in token for part in ("embed", "embedding", "e5-", "bge-")):
        return CAPABILITY_EMBEDDINGS
    if any(part in token for part in ("image", "vision", "sdxl", "flux", "dall-e", "stable-diffusion")):
        return CAPABILITY_IMAGE
    if any(part in token for part in ("audio", "whisper", "tts", "speech", "asr")):
        return CAPABILITY_AUDIO
    if any(part in token for part in ("video", "luma", "runway", "sora")):
        return CAPABILITY_VIDEO
    if any(part in token for part in ("gpt", "llama", "gemma", "mistral", "claude", "qwen", "nemotron", "instruct", "chat")):
        return CAPABILITY_CHAT
    return CAPABILITY_UNKNOWN


def build_capability_inventory(model_ids: list[str]) -> dict[str, Any]:
    """Build a secret-free capability inventory from discovered model ids.

    Offline-only: classifies each id via :func:`classify_model_capability_hint`.
    ``measurement_status`` is always ``offline_capability_hints`` so operators
    never confuse this with a live probe.
    """
    rows: list[dict[str, str]] = []
    for model_id in sorted({mid.strip() for mid in model_ids if isinstance(mid, str) and mid.strip()}):
        rows.append(
            {
                "model_id": model_id,
                "capability_hint": classify_model_capability_hint(model_id),
            }
        )
    by_capability: dict[str, int] = {}
    for row in rows:
        label = row["capability_hint"]
        by_capability[label] = by_capability.get(label, 0) + 1
    return {
        "measurement_status": "offline_capability_hints",
        "model_count": len(rows),
        "capability_rows": rows,
        "capability_counts": dict(sorted(by_capability.items())),
    }


def build_benchmark_plan_dry_run(
    model_ids: list[str],
    *,
    task_manifest_id: str = "locked_eval_v1",
    max_steps: int = 5,
    hard_request_budget: int = 100,
) -> dict[str, Any]:
    """Return a fail-closed dry-run benchmark plan for issue #86 fair comparisons.

    Never attaches secrets. Hypothetical cost fields stay ``unknown`` until a
    versioned pricing scenario exists (honest cost reporting — never invent zero).
    Policies cover direct worker, route_once, bounded conduct, and hindsight
    best-single baselines per the product research contract.
    """
    if max_steps < 1 or max_steps > 5:
        raise NimDiscoveryError("max_steps must be between 1 and 5 for Conductor/TRINITY-bounded dry runs")
    if hard_request_budget < 1:
        raise NimDiscoveryError("hard_request_budget must be >= 1")
    if not isinstance(task_manifest_id, str) or not task_manifest_id.strip():
        raise NimDiscoveryError("task_manifest_id must be a non-empty string")

    chat_eligible = [
        mid
        for mid in sorted({m.strip() for m in model_ids if isinstance(m, str) and m.strip()})
        if classify_model_capability_hint(mid) in {CAPABILITY_CHAT, CAPABILITY_UNKNOWN}
    ]
    inventory = build_capability_inventory(model_ids)
    cells: list[dict[str, Any]] = []
    # Worst-case provider calls per chat-eligible model:
    # direct_worker=1, route_once=1, bounded_conduct<=max_steps.
    # hindsight_best_single reuses direct scores (zero extra egress).
    per_model_call_budget = 1 + 1 + max_steps
    planned_calls = len(chat_eligible) * per_model_call_budget
    for policy_name in _BENCHMARK_POLICY_NAMES:
        for model_id in chat_eligible:
            cells.append(
                {
                    "policy_name": policy_name,
                    "model_id": model_id,
                    "task_manifest_id": task_manifest_id.strip(),
                    "max_steps": max_steps,
                    "planned_provider_calls": (
                        max_steps if policy_name == "bounded_conduct" else (
                            0 if policy_name == "hindsight_best_single" else 1
                        )
                    ),
                    "actual_api_cost": "unknown",
                    "hypothetical_paid_cost": "unknown",
                    "pricing_scenario_id": None,
                }
            )

    fits_budget = planned_calls <= hard_request_budget
    return {
        "measurement_status": "dry_run_plan",
        "task_manifest_id": task_manifest_id.strip(),
        "max_steps": max_steps,
        "hard_request_budget": hard_request_budget,
        "planned_request_count": planned_calls,
        "per_model_call_budget": per_model_call_budget,
        "fits_hard_request_budget": fits_budget,
        "chat_eligible_model_count": len(chat_eligible),
        "capability_inventory": inventory,
        "comparison_cells": cells,
        "admission_status": "admitted" if fits_budget else "rejected_budget_exceeded",
    }


# Probe outcome labels for issue #86 capability inventory (offline dry-run + live opt-in).
PROBE_OUTCOME_CHAT = "chat"
PROBE_OUTCOME_EMBEDDINGS = "embeddings"
PROBE_OUTCOME_IMAGE = "image"
PROBE_OUTCOME_AUDIO = "audio"
PROBE_OUTCOME_VIDEO = "video"
PROBE_OUTCOME_UNSUPPORTED = "unsupported"
PROBE_OUTCOME_RATE_LIMITED = "rate_limited"
PROBE_OUTCOME_UNAVAILABLE = "unavailable"
PROBE_OUTCOME_TIMEOUT = "timeout"
PROBE_OUTCOME_MALFORMED = "malformed"
PROBE_OUTCOME_FAILED = "failed"
PROBE_OUTCOME_SKIPPED = "skipped"

_PROBE_OUTCOMES = frozenset(
    {
        PROBE_OUTCOME_CHAT,
        PROBE_OUTCOME_EMBEDDINGS,
        PROBE_OUTCOME_IMAGE,
        PROBE_OUTCOME_AUDIO,
        PROBE_OUTCOME_VIDEO,
        PROBE_OUTCOME_UNSUPPORTED,
        PROBE_OUTCOME_RATE_LIMITED,
        PROBE_OUTCOME_UNAVAILABLE,
        PROBE_OUTCOME_TIMEOUT,
        PROBE_OUTCOME_MALFORMED,
        PROBE_OUTCOME_FAILED,
        PROBE_OUTCOME_SKIPPED,
    }
)


def classify_probe_http_status(status_code: int) -> str:
    """Map an HTTP status from a capability probe to a machine-readable outcome."""
    if not isinstance(status_code, int) or isinstance(status_code, bool):
        raise NimDiscoveryError("probe status_code must be an int")
    if status_code == 200:
        return PROBE_OUTCOME_CHAT  # refined by response body shape in classify_probe_result
    if status_code == 429:
        return PROBE_OUTCOME_RATE_LIMITED
    if status_code in (401, 403):
        return PROBE_OUTCOME_UNAVAILABLE
    if status_code == 404:
        return PROBE_OUTCOME_UNSUPPORTED
    if status_code == 408 or status_code == 504:
        return PROBE_OUTCOME_TIMEOUT
    if 400 <= status_code < 500:
        return PROBE_OUTCOME_UNSUPPORTED
    if 500 <= status_code < 600:
        return PROBE_OUTCOME_FAILED
    raise NimDiscoveryError(f"unsupported probe status_code: {status_code}")


def classify_probe_result(
    *,
    model_id: str,
    probe_kind: str,
    status_code: int,
    body: Any | None = None,
    error_class: str | None = None,
) -> dict[str, Any]:
    """Classify one capability probe into a secret-free evidence row.

    Offline dry-run supplies fixture status/body; live probes (opt-in) reuse the
    same classifier. Never embeds credentials or raw provider secrets.
    """
    if not isinstance(model_id, str) or not model_id.strip():
        raise NimDiscoveryError("model_id must be a non-empty string")
    if not isinstance(probe_kind, str) or not probe_kind.strip():
        raise NimDiscoveryError("probe_kind must be a non-empty string")
    kind = probe_kind.strip().lower()
    if error_class:
        err = str(error_class)
        if "timeout" in err.lower() or err in {"TimeoutError", "socket.timeout"}:
            outcome = PROBE_OUTCOME_TIMEOUT
        else:
            outcome = PROBE_OUTCOME_FAILED
        return {
            "model_id": model_id.strip(),
            "probe_kind": kind,
            "status_code": status_code if isinstance(status_code, int) else None,
            "outcome": outcome,
            "error_class": err,
            "skip_reason": None,
        }

    status_outcome = classify_probe_http_status(status_code)
    if status_outcome != PROBE_OUTCOME_CHAT:
        return {
            "model_id": model_id.strip(),
            "probe_kind": kind,
            "status_code": status_code,
            "outcome": status_outcome,
            "error_class": None,
            "skip_reason": None,
        }

    # 200: refine by body shape when present.
    if body is None:
        outcome = {
            "chat": PROBE_OUTCOME_CHAT,
            "embeddings": PROBE_OUTCOME_EMBEDDINGS,
            "image": PROBE_OUTCOME_IMAGE,
            "audio": PROBE_OUTCOME_AUDIO,
            "video": PROBE_OUTCOME_VIDEO,
        }.get(kind, PROBE_OUTCOME_CHAT)
    elif not isinstance(body, dict):
        outcome = PROBE_OUTCOME_MALFORMED
    elif kind == "embeddings" and isinstance(body.get("data"), list):
        outcome = PROBE_OUTCOME_EMBEDDINGS
    elif kind == "chat" and isinstance(body.get("choices"), list) and body.get("choices"):
        outcome = PROBE_OUTCOME_CHAT
    elif kind in {"image", "audio", "video"} and body:
        outcome = {
            "image": PROBE_OUTCOME_IMAGE,
            "audio": PROBE_OUTCOME_AUDIO,
            "video": PROBE_OUTCOME_VIDEO,
        }[kind]
    else:
        outcome = PROBE_OUTCOME_MALFORMED

    return {
        "model_id": model_id.strip(),
        "probe_kind": kind,
        "status_code": status_code,
        "outcome": outcome,
        "error_class": None,
        "skip_reason": None,
    }


def build_capability_probe_plan(
    model_ids: list[str],
    *,
    hard_request_budget: int = 100,
    probe_kinds: tuple[str, ...] = ("chat", "embeddings"),
) -> dict[str, Any]:
    """Build a fail-closed dry-run probe plan for discovered model ids.

    Does not perform network I/O. Planned probe count = models x probe_kinds.
    """
    if hard_request_budget < 1:
        raise NimDiscoveryError("hard_request_budget must be >= 1")
    if not probe_kinds:
        raise NimDiscoveryError("probe_kinds must be non-empty")
    for kind in probe_kinds:
        if not isinstance(kind, str) or not kind.strip():
            raise NimDiscoveryError("probe_kinds entries must be non-empty strings")
    unique_ids = sorted({m.strip() for m in model_ids if isinstance(m, str) and m.strip()})
    kinds = tuple(k.strip().lower() for k in probe_kinds)
    planned = len(unique_ids) * len(kinds)
    cells = [
        {
            "model_id": mid,
            "probe_kind": kind,
            "planned_provider_calls": 1,
            "hint": classify_model_capability_hint(mid),
        }
        for mid in unique_ids
        for kind in kinds
    ]
    fits = planned <= hard_request_budget
    return {
        "measurement_status": "offline_probe_plan",
        "hard_request_budget": hard_request_budget,
        "planned_request_count": planned,
        "fits_hard_request_budget": fits,
        "admission_status": "admitted" if fits else "rejected_budget_exceeded",
        "model_count": len(unique_ids),
        "probe_kinds": list(kinds),
        "probe_cells": cells,
    }


def run_capability_probes_dry_run(
    fixture_rows: list[dict[str, Any]],
    *,
    hard_request_budget: int = 100,
) -> dict[str, Any]:
    """Execute offline capability probes from fixture rows (no network, no secrets).

    Each fixture row must include ``model_id``, ``probe_kind``, and either
    ``status_code`` or ``error_class``. Optional ``body`` refines 200 outcomes.
    """
    if hard_request_budget < 1:
        raise NimDiscoveryError("hard_request_budget must be >= 1")
    if not isinstance(fixture_rows, list):
        raise NimDiscoveryError("fixture_rows must be a list")
    if len(fixture_rows) > hard_request_budget:
        raise NimDiscoveryError(
            f"fixture probe count {len(fixture_rows)} exceeds hard_request_budget {hard_request_budget}"
        )

    results: list[dict[str, Any]] = []
    for index, row in enumerate(fixture_rows):
        if not isinstance(row, dict):
            raise NimDiscoveryError(f"fixture row {index} must be an object")
        model_id = row.get("model_id")
        probe_kind = row.get("probe_kind")
        if row.get("error_class"):
            classified = classify_probe_result(
                model_id=str(model_id or ""),
                probe_kind=str(probe_kind or "chat"),
                status_code=0,
                error_class=str(row["error_class"]),
            )
        else:
            status = row.get("status_code")
            if not isinstance(status, int) or isinstance(status, bool):
                raise NimDiscoveryError(f"fixture row {index} needs int status_code or error_class")
            classified = classify_probe_result(
                model_id=str(model_id or ""),
                probe_kind=str(probe_kind or "chat"),
                status_code=status,
                body=row.get("body"),
            )
        results.append(classified)

    by_outcome: dict[str, int] = {}
    for row in results:
        by_outcome[row["outcome"]] = by_outcome.get(row["outcome"], 0) + 1

    chat_eligible = sorted(
        {
            r["model_id"]
            for r in results
            if r["outcome"] == PROBE_OUTCOME_CHAT and r["probe_kind"] == "chat"
        }
    )
    return {
        "measurement_status": "offline_probe_results",
        "probe_count": len(results),
        "outcome_counts": dict(sorted(by_outcome.items())),
        "chat_eligible_model_ids": chat_eligible,
        "probe_rows": results,
        "hard_request_budget": hard_request_budget,
        "fits_hard_request_budget": True,
        "admission_status": "admitted",
        "notes": (
            "Offline fixture classification only — not live NIM probe evidence. "
            "Live probes require RUN_LIVE_NIM_TESTS=1 and NVIDIA_NIM_API_KEY via KV."
        ),
    }
