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

from .credentials import get_credential

DEFAULT_NIM_MODELS_URL = "https://integrate.api.nvidia.com/v1/models"
NIM_CREDENTIAL_NAME = "NVIDIA_NIM_API_KEY"


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
        Absolute HTTPS URL of the models listing endpoint.
    credential_name:
        KV credential name. Defaults to ``NVIDIA_NIM_API_KEY``.
    timeout_seconds:
        Socket timeout for the listing request.
    transport:
        Optional callable ``(request, timeout) -> bytes`` for tests. When omitted,
        uses stdlib ``urllib`` with default TLS verification.

    Returns
    -------
    dict
        ``measurement_status`` (``live_nim_catalog`` | ``offline_fixture`` |
        ``credential_missing``), ``model_ids`` (sorted unique strings), and
        ``source_url``. Never includes the raw API key.
    """
    api_key = get_credential(credential_name)
    if not api_key:
        return {
            "measurement_status": "credential_missing",
            "model_ids": [],
            "source_url": models_url,
            "credential_name": credential_name,
        }

    request = urllib.request.Request(
        models_url,
        headers={
            "authorization": f"Bearer {api_key}",
            "accept": "application/json",
        },
        method="GET",
    )

    if transport is not None:
        raw = transport(request, timeout_seconds)
    else:
        context = ssl.create_default_context()
        with urllib.request.urlopen(  # nosec B310 - URL is operator-configured HTTPS catalog endpoint.
            request, timeout=timeout_seconds, context=context
        ) as response:
            raw = response.read()

    payload = json.loads(raw.decode("utf-8"))
    model_ids = _extract_model_ids(payload)
    return {
        "measurement_status": "live_nim_catalog",
        "model_ids": model_ids,
        "source_url": models_url,
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

    Each model becomes one agent. After ``model_group`` race lands on main
    (issue #102 / PR #114), operators may add ``model_group`` keys for replica race.
    """
    entries: list[dict[str, Any]] = []
    for index, model_id in enumerate(model_ids):
        slug = _slug_model_id(model_id)
        entries.append(
            {
                "id": f"nim_{slug}_agent",
                "model": model_id,
                "base_url": base_url,
                "credential_key": credential_key,
                "tags": list(tags),
                "priority": max(0, 10 - index),
            }
        )
    return entries


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
