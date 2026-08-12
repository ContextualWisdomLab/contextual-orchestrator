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
            raw = response.read()
        status = "live_nim_catalog"

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
    for policy_name in _BENCHMARK_POLICY_NAMES:
        for model_id in chat_eligible:
            cells.append(
                {
                    "policy_name": policy_name,
                    "model_id": model_id,
                    "task_manifest_id": task_manifest_id.strip(),
                    "max_steps": max_steps,
                    "actual_api_cost": "unknown",
                    "hypothetical_paid_cost": "unknown",
                    "pricing_scenario_id": None,
                }
            )

    planned_calls = len(cells)
    fits_budget = planned_calls <= hard_request_budget
    return {
        "measurement_status": "dry_run_plan",
        "task_manifest_id": task_manifest_id.strip(),
        "max_steps": max_steps,
        "hard_request_budget": hard_request_budget,
        "planned_request_count": planned_calls,
        "fits_hard_request_budget": fits_budget,
        "chat_eligible_model_count": len(chat_eligible),
        "capability_inventory": inventory,
        "comparison_cells": cells,
        "admission_status": "admitted" if fits_budget else "rejected_budget_exceeded",
    }
