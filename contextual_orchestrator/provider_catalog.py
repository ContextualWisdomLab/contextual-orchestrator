"""Production provider catalog: KV secrets, live GET /v1/models, static fallback.

After each org secret is registered, the primary path is that host's
OpenAI-compatible ``GET /v1/models`` using ``get_credential`` — never
``os.getenv`` at request time. The static seed
(``examples/agents.production.json``) is only a fallback when a provider has
no list API, the list call 401/403/404/429/5xxs, or the body is empty/malformed
(``docs/doctoring/provider-catalog.md``). GitHub Models stay out of catalog.
"""

from __future__ import annotations

import ipaddress
import os
import re
import socket
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .credentials import get_credential, register_credential
from .orchestrator import (
    FORBIDDEN_CREDENTIAL_NAMES,
    FORBIDDEN_HOST_MARKERS,
    FORBIDDEN_MODEL_MARKERS,
    ModelAgent,
    ModelClient,
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
    "embed",
    "rerank",
    "whisper",
    "tts",
    "dall-e",
    "dalle",
    "moderation",
    "transcri",
    "image",
    "audio",
    "flux",
    "sdxl",
    "stable-diffusion",
)
_DISCOVERY_CAP = 32
_CODING_NAME_MARKERS = (
    "code",
    "coder",
    "starcoder",
    "codellama",
    "nemotron",
    "qwen",
    "deepseek",
    "claude",
    "gpt",
    "sonnet",
    "implement",
)
_REVIEW_NAME_MARKERS = ("review", "guard", "safety", "critic", "verify")
_REASONING_NAME_MARKERS = (
    "reason",
    "think",
    "nemotron",
    "gpt",
    "claude",
    "sonnet",
    "o1",
    "o3",
    "o4",
    "r1",
)
_CHEAP_NAME_MARKERS = ("mini", "nano", "small", "haiku", "flash", "-4b", "-7b", "-8b", "-3b")

ORG_PROVIDER_SPECS: tuple[dict[str, str], ...] = (
    {
        "credential_name": "NVIDIA_NIM_API_KEY",
        "base_url": NIM_INTEGRATE_BASE_URL,
        "provider_name": "nvidia_nim",
    },
    {
        "credential_name": "NVIDIA_NIM_API_KEY_SUB",
        "base_url": NIM_INTEGRATE_BASE_URL,
        "provider_name": "nvidia_nim",
    },
    {
        "credential_name": "OPENAI_API_KEY",
        "base_url": OPENAI_API_BASE_URL,
        "provider_name": "openai",
    },
    {
        "credential_name": "OPENROUTER_API_KEY",
        "base_url": OPENROUTER_API_BASE_URL,
        "provider_name": "openrouter",
    },
    {
        "credential_name": "BYTEZ_API_KEY",
        "base_url": BYTEZ_OPENAI_BASE_URL,
        "provider_name": "bytez",
    },
)


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

    Malformed bodies return an empty list so that provider falls back to the
    static seed. Embedding/audio/image/rerank ids and retired GitHub Models
    names are dropped. A successful list is the live catalog.
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
        if "github" in lowered or "copilot" in lowered:
            continue
        if model_id in seen:
            continue
        seen.add(model_id)
        models.append(model_id)
    return models


def _catalog_list_target(
    base_url: str, *, allow_insecure: bool
) -> tuple[str, str, int, str] | None:
    """Return ``(scheme, hostname, port, prefix)`` for GET /models, or None if unsafe.

    Only http(s) hosts are allowed. Private/loopback/reserved addresses are
    rejected unless ``allow_insecure`` (lab fixtures). ``file://`` is never a
    list target.
    """
    parsed = urlparse(base_url)
    hostname = parsed.hostname
    if not hostname or parsed.scheme not in {"https", "http"}:
        return None
    if not allow_insecure and parsed.scheme != "https":
        return None
    prefix = parsed.path.rstrip("/")
    if prefix and (not prefix.startswith("/") or prefix.startswith("//") or "\r" in prefix or "\n" in prefix):
        return None
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if not allow_insecure:
        try:
            for address in socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM):
                ip_address = ipaddress.ip_address(address[4][0])
                if (
                    ip_address.is_private
                    or ip_address.is_loopback
                    or ip_address.is_link_local
                    or ip_address.is_multicast
                    or ip_address.is_reserved
                ):
                    return None
        except OSError:
            return None
    return parsed.scheme, hostname, port, prefix


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
    Uses ``ModelClient.fetch_provider_json`` so discovery does not open a
    second HTTP client (Semgrep ``httpsconnection-detected`` / dynamic urllib).
    """
    if not get_credential(credential_name):
        return []
    target = _catalog_list_target(base_url, allow_insecure=allow_insecure)
    if target is None:
        return []
    scheme, hostname, port, prefix = target
    agent = ModelAgent(
        "catalog_discovery_agent",
        "catalog_list",
        f"{scheme}://{hostname}:{port}{prefix}",
        credential_key=credential_name,
    )
    try:
        payload = ModelClient(
            timeout=timeout,
            verify_tls=not allow_insecure,
        ).fetch_provider_json(agent, "/models")
    except Exception:  # noqa: BLE001 - discovery must never break bootstrap
        return []
    return _cap_chat_models(parse_models_list(payload), _DISCOVERY_CAP)


def tag_discovered_model(model: str, *, credential_name: str = "") -> tuple[str, ...]:
    """Assign Fugu / TRINITY / Conductor tags from the model id. No prices."""
    lowered = model.lower()
    tags: list[str] = []
    if any(marker in lowered for marker in _CODING_NAME_MARKERS):
        tags.append("coding")
    if any(marker in lowered for marker in _REVIEW_NAME_MARKERS) or "coding" in tags:
        tags.append("review")
    if any(marker in lowered for marker in _REASONING_NAME_MARKERS) or "reasoning" not in tags:
        tags.append("reasoning")
    if any(marker in lowered for marker in _CHEAP_NAME_MARKERS):
        tags.append("cheap")
    if credential_name.endswith("_SUB"):
        tags.append("fallback")
    return tuple(dict.fromkeys(tags))


def _cap_chat_models(models: list[str], cap: int) -> list[str]:
    """Keep coding/review/reasoning-named chat ids first when a vendor dumps hundreds."""
    preferred = [
        model
        for model in models
        if set(tag_discovered_model(model)) & {"coding", "review", "reasoning"}
    ]
    rest = [model for model in models if model not in preferred]
    return (preferred + rest)[:cap]


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


def _provider_slots(seed: list[ModelAgent]) -> list[tuple[str, str, str, list[ModelAgent]]]:
    """One slot per org credential (and any extra seed credentials). Seed may override URL."""
    by_credential: dict[str, list[ModelAgent]] = {}
    for agent in seed:
        by_credential.setdefault(agent.credential_name, []).append(agent)
    slots: list[tuple[str, str, str, list[ModelAgent]]] = []
    seen: set[str] = set()
    for spec in ORG_PROVIDER_SPECS:
        credential_name = spec["credential_name"]
        rows = by_credential.get(credential_name, [])
        base_url = rows[0].base_url if rows else spec["base_url"]
        provider_name = (rows[0].provider_name if rows and rows[0].provider_name else spec["provider_name"])
        slots.append((credential_name, base_url, provider_name, rows))
        seen.add(credential_name)
    for credential_name, rows in by_credential.items():
        if credential_name in seen:
            continue
        slots.append((credential_name, rows[0].base_url, rows[0].provider_name or "discovered", rows))
    return slots


def _agents_from_discovered_models(
    *,
    models: list[str],
    base_url: str,
    credential_name: str,
    provider_name: str,
    existing_ids: set[str],
) -> list[ModelAgent]:
    """Build live-pool workers from a successful list response. Seed order is unused."""
    agents: list[ModelAgent] = []
    for model in models:
        if not catalog_allows_fields(base_url, model, credential_name):
            continue
        agent_id = _discovered_agent_id(provider_name, model, existing_ids)
        agents.append(
            ModelAgent(
                id=agent_id,
                model=model,
                base_url=base_url,
                credential_key=credential_name,
                tags=tag_discovered_model(model, credential_name=credential_name),
                provider_name=provider_name,
            )
        )
        existing_ids.add(agent_id)
    return agents


def compose_provider_catalog(
    seed: list[ModelAgent],
    *,
    discover: bool = False,
    allow_insecure_discovery: bool = False,
) -> tuple[list[ModelAgent], list[dict[str, str]]]:
    """Compose the live pool: discovered chat models win; seed is fallback only.

    When ``discover`` is false the seed rows with a resolvable credential are
    kept (offline tests). When true, each org secret triggers ``GET /models``
    and a successful chat list replaces that provider's seed rows.
    """
    ready: list[ModelAgent] = []
    skipped: list[dict[str, str]] = []
    existing_ids: set[str] = set()
    if not discover:
        for agent in seed:
            if not catalog_allows_agent(agent):
                skipped.append({"id": agent.id, "reason": "forbidden_provider"})
                continue
            if agent.base_url.startswith("mock://") or get_credential(agent.credential_name):
                ready.append(agent)
            else:
                skipped.append({"id": agent.id, "reason": "credential_missing"})
        return ready, skipped

    for credential_name, base_url, provider_name, seed_rows in _provider_slots(seed):
        allowed_seed = [agent for agent in seed_rows if catalog_allows_agent(agent)]
        for agent in seed_rows:
            if agent not in allowed_seed:
                skipped.append({"id": agent.id, "reason": "forbidden_provider"})
        if base_url.startswith("mock://"):
            ready.extend(allowed_seed)
            existing_ids.update(agent.id for agent in allowed_seed)
            continue
        if get_credential(credential_name) is None:
            for agent in allowed_seed:
                skipped.append({"id": agent.id, "reason": "credential_missing"})
            if not allowed_seed:
                skipped.append({"id": credential_name.lower(), "reason": "credential_missing"})
            continue
        insecure = allow_insecure_discovery or urlparse(base_url).scheme == "http"
        models = discover_provider_models(base_url, credential_name, allow_insecure=insecure)
        if models:
            ready.extend(
                _agents_from_discovered_models(
                    models=models,
                    base_url=base_url,
                    credential_name=credential_name,
                    provider_name=provider_name,
                    existing_ids=existing_ids,
                )
            )
            continue
        if allowed_seed:
            ready.extend(allowed_seed)
            existing_ids.update(agent.id for agent in allowed_seed)
        else:
            skipped.append({"id": credential_name.lower(), "reason": "discovery_empty"})
    return ready, skipped


def persist_catalog_to_agents_db(agents: list[ModelAgent], path: str) -> None:
    """Write ready agents into the sqlite agent-pool store used by ``--agents-db``."""
    store = _AgentPoolStore(path)
    try:
        for agent in agents:
            store.save(agent)
    finally:
        store.close()


def bootstrap_org_catalog(
    *,
    seed_agents: list[ModelAgent] | None = None,
    seed_path: str | Path | None = None,
    agents_db: str | None = None,
    discover: bool = True,
    allow_insecure_discovery: bool = False,
) -> tuple[list[ModelAgent], dict[str, Any]]:
    """Register present org secrets, discover chat models, persist, and return the pool."""
    credentials = register_org_credentials_from_env(skip_missing=True)
    agents = seed_agents if seed_agents is not None else load_production_seed(seed_path)
    ready, skipped = compose_provider_catalog(
        agents, discover=discover, allow_insecure_discovery=allow_insecure_discovery
    )
    if agents_db and ready:
        persist_catalog_to_agents_db(ready, agents_db)
    report = {
        "registered_credentials": credentials["registered"],
        "skipped_credentials": credentials["skipped"],
        "ready_agents": [
            {"id": agent.id, "model": agent.model, "credential_key": agent.credential_name}
            for agent in ready
        ],
        "skipped_agents": skipped,
        "agents_db": agents_db,
        "discovery": "primary" if discover else "disabled",
    }
    return ready, report


def seed_provider_catalog(
    *,
    seed_agents: list[ModelAgent] | None = None,
    seed_path: str | Path | None = None,
    agents_db: str | None = None,
    discover: bool = True,
    allow_insecure_discovery: bool = False,
) -> dict[str, Any]:
    """Register present org secrets, compose the ready pool, and optionally persist it."""
    _ready, report = bootstrap_org_catalog(
        seed_agents=seed_agents,
        seed_path=seed_path,
        agents_db=agents_db,
        discover=discover,
        allow_insecure_discovery=allow_insecure_discovery,
    )
    return report
