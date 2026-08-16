"""Production provider catalog: org secrets, static seed, and optional /v1/models discovery.

The catalog is data (``examples/agents.production.json``) plus a bootstrap
adapter. Runtime provider keys still resolve only through ``get_credential``.
Environment variables are bootstrap transport into the KV — the same seam as
``register-credential --from-env`` (see ``docs/kv-credentials.md``).

A missing secret skips that upstream and keeps the rest of the pool serving.
GitHub Models / Copilot tokens are rejected. Providers that expose
``GET /v1/models`` can auto-register chat models; providers without a list API
keep the paper-justified static seed (``docs/doctoring/provider-catalog.md``).
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .credentials import get_credential, register_credential
from .orchestrator import (
    FORBIDDEN_CREDENTIAL_NAMES,
    FORBIDDEN_HOST_MARKERS,
    FORBIDDEN_MODEL_MARKERS,
    ModelAgent,
    _AgentPoolStore,
    catalog_allows_fields,
    load_agents,
)

ORG_CREDENTIAL_NAMES: tuple[str, ...] = (
    "NVIDIA_NIM_API_KEY",
    "NVIDIA_NIM_API_KEY_SUB",
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "BYTEZ_API_KEY",
)

NIM_INTEGRATE_BASE_URL = "https://integrate.api.nvidia.com/v1"
OPENAI_API_BASE_URL = "https://api.openai.com/v1"
OPENROUTER_API_BASE_URL = "https://openrouter.ai/api/v1"
BYTEZ_OPENAI_BASE_URL = "https://api.bytez.com/models/v2/openai/v1"

PRODUCTION_SEED_PATH = Path(__file__).resolve().parents[1] / "examples" / "agents.production.json"

_NON_CHAT_MODEL_MARKERS = (
    "embedding",
    "whisper",
    "tts",
    "dall-e",
    "dalle",
    "moderation",
    "transcri",
    "tts-1",
)
_DISCOVERY_CAP = 16


def catalog_allows_agent(agent_or_mapping: ModelAgent | dict[str, Any]) -> bool:
    """Return True when a seed row or ``ModelAgent`` is not a GitHub Models target."""
    if isinstance(agent_or_mapping, dict):
        credential_name = str(
            agent_or_mapping.get("api_key_env") or agent_or_mapping.get("credential_key") or ""
        )
        return catalog_allows_fields(
            str(agent_or_mapping.get("base_url", "")),
            str(agent_or_mapping.get("model", "")),
            credential_name,
        )
    return catalog_allows_fields(
        agent_or_mapping.base_url,
        agent_or_mapping.model,
        agent_or_mapping.credential_name,
    )


def load_production_seed(path: str | Path | None = None) -> list[ModelAgent]:
    """Load the default production agent catalog (not the mock-only example)."""
    return load_agents(str(path or PRODUCTION_SEED_PATH))


def register_org_credentials_from_env(*, skip_missing: bool = True) -> dict[str, list[str]]:
    """Register the five org Actions secrets from env into the KV (bootstrap only).

    Missing names are skipped when ``skip_missing`` is true so a partial secret
    set still yields a serving pool. This is the single allowed ``os.environ``
    read of provider key *values* — deploy/CI injects them into this one-shot
    process; request-time resolution stays on ``get_credential``.
    """
    registered: list[str] = []
    skipped: list[str] = []
    for name in ORG_CREDENTIAL_NAMES:
        value = os.environ.get(name)
        if value:
            register_credential(name, value)
            registered.append(name)
        else:
            skipped.append(name)
            if not skip_missing:
                raise RuntimeError(f"{name} is not set for bootstrap transport")
    return {"registered": registered, "skipped": skipped}


def parse_models_list(payload: Any) -> list[str]:
    """Extract chat model ids from an OpenAI-shaped ``/v1/models`` payload.

    Malformed bodies return an empty list (static seed remains the claim
    boundary). Embedding/audio/image ids and retired GitHub Models names are
    dropped.
    """
    if not isinstance(payload, dict):
        return []
    rows = payload.get("data")
    if not isinstance(rows, list):
        return []
    models: list[str] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        model_id = row.get("id")
        if not isinstance(model_id, str) or not model_id.strip():
            continue
        lowered = model_id.lower()
        if any(marker in lowered for marker in _NON_CHAT_MODEL_MARKERS):
            continue
        if any(marker in lowered for marker in FORBIDDEN_MODEL_MARKERS):
            continue
        if model_id in seen:
            continue
        seen.add(model_id)
        models.append(model_id)
    return models


def discover_provider_models(
    base_url: str,
    credential_name: str,
    *,
    allow_insecure: bool = False,
    timeout: float = 10.0,
) -> list[str]:
    """GET ``{base_url}/models`` with the KV credential; return chat model ids.

    Any transport, HTTP, or parse failure returns ``[]`` so the static seed
    stays in force. ``allow_insecure`` is a lab/test hook for loopback fixtures.
    """
    api_key = get_credential(credential_name)
    if not api_key:
        return []
    parsed = urlparse(base_url)
    if not parsed.hostname:
        return []
    if not allow_insecure and parsed.scheme != "https":
        return []
    request = Request(
        f"{base_url.rstrip('/')}/models",
        headers={"authorization": f"Bearer {api_key}", "accept": "application/json"},
        method="GET",
    )
    try:
        with urlopen(request, timeout=timeout) as response:  # nosec B310 - caller supplies a catalog base_url already used for chat.
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:  # noqa: BLE001 - discovery must never break bootstrap
        return []
    return parse_models_list(payload)[:_DISCOVERY_CAP]


def _discovered_agent_id(provider_name: str, model: str, existing: set[str]) -> str:
    """Build a two-or-more-word snake_case id for a discovered chat model."""
    provider = re.sub(r"[^a-z0-9]+", "_", (provider_name or "discovered").lower()).strip("_") or "discovered"
    slug = re.sub(r"[^a-z0-9]+", "_", model.lower()).strip("_") or "model"
    base = f"{provider}_{slug}"
    if len(base) > 80:
        base = base[:80].rstrip("_")
    candidate = base
    suffix = 2
    while candidate in existing:
        candidate = f"{base}_{suffix}"
        suffix += 1
    return candidate


def compose_provider_catalog(
    seed: list[ModelAgent],
    *,
    discover: bool = False,
    allow_insecure_discovery: bool = False,
) -> tuple[list[ModelAgent], list[dict[str, str]]]:
    """Keep agents whose KV credential is present; optionally append discovered chat models."""
    ready: list[ModelAgent] = []
    skipped: list[dict[str, str]] = []
    for agent in seed:
        if not catalog_allows_agent(agent):
            skipped.append({"id": agent.id, "reason": "forbidden_provider"})
            continue
        if agent.base_url.startswith("mock://") or get_credential(agent.credential_name):
            ready.append(agent)
        else:
            skipped.append({"id": agent.id, "reason": "credential_missing"})
    if discover:
        seen_models = {(agent.base_url, agent.model) for agent in ready}
        existing_ids = {agent.id for agent in ready}
        templates: dict[tuple[str, str], ModelAgent] = {}
        for agent in ready:
            templates.setdefault((agent.base_url, agent.credential_name), agent)
        for (base_url, credential_name), template in templates.items():
            insecure = allow_insecure_discovery or urlparse(base_url).scheme == "http"
            for model in discover_provider_models(
                base_url, credential_name, allow_insecure=insecure
            ):
                if (base_url, model) in seen_models:
                    continue
                if not catalog_allows_fields(base_url, model, credential_name):
                    continue
                agent_id = _discovered_agent_id(template.provider_name, model, existing_ids)
                discovered = ModelAgent(
                    id=agent_id,
                    model=model,
                    base_url=base_url,
                    credential_key=credential_name,
                    tags=template.tags,
                    priority=max(0, template.priority - 1),
                    provider_name=template.provider_name,
                )
                ready.append(discovered)
                existing_ids.add(agent_id)
                seen_models.add((base_url, model))
    return ready, skipped


def persist_catalog_to_agents_db(agents: list[ModelAgent], path: str) -> None:
    """Write ready agents into the sqlite agent-pool store used by ``--agents-db``."""
    store = _AgentPoolStore(path)
    try:
        for agent in agents:
            store.save(agent)
    finally:
        store.close()


def seed_provider_catalog(
    *,
    seed_agents: list[ModelAgent] | None = None,
    seed_path: str | Path | None = None,
    agents_db: str | None = None,
    discover: bool = False,
    allow_insecure_discovery: bool = False,
) -> dict[str, Any]:
    """Register present org secrets, compose the ready pool, and optionally persist it."""
    credentials = register_org_credentials_from_env(skip_missing=True)
    agents = seed_agents if seed_agents is not None else load_production_seed(seed_path)
    ready, skipped = compose_provider_catalog(
        agents, discover=discover, allow_insecure_discovery=allow_insecure_discovery
    )
    if agents_db and ready:
        persist_catalog_to_agents_db(ready, agents_db)
    return {
        "registered_credentials": credentials["registered"],
        "skipped_credentials": credentials["skipped"],
        "ready_agents": [
            {"id": agent.id, "model": agent.model, "credential_key": agent.credential_name}
            for agent in ready
        ],
        "skipped_agents": skipped,
        "agents_db": agents_db,
    }
