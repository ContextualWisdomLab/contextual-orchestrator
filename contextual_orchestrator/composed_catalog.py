"""Default-on composed catalog: discover when a KV credential is present.

This slice does **not** own PR #642's production seed, ``--discover-models``
flag, OpenCode sidecar, or 429→next-agent failover. It owns:

* discovery as the **default** when ``get_credential(name)`` is set
* a static fallback **only** when ``GET /v1/models`` fails
* the OpenAI-shaped list payload for this gateway's own ``GET /v1/models``
* exception-robust per-provider isolation (one failure never aborts compose)

Runtime keys resolve only through ``get_credential``. GitHub Models hosts and
``COPILOT_GITHUB_TOKEN`` are rejected. See ``docs/doctoring/priced-selection.md``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable
from urllib.parse import urlparse

from .conventions import require_object_name
from .credentials import get_credential
from .orchestrator import ModelAgent, ModelClient, allowed_provider_hosts
from .provider_egress import provider_base_url_rejection

ORG_CREDENTIAL_NAMES: tuple[str, ...] = (
    "NVIDIA_NIM_API_KEY",
    "NVIDIA_NIM_API_KEY_SUB",
    "BYTEZ_API_KEY",
    "OPENROUTER_API_KEY",
    "OPENAI_API_KEY",
)

FORBIDDEN_CREDENTIAL_NAMES = frozenset({"COPILOT_GITHUB_TOKEN"})
FORBIDDEN_HOST_MARKERS = frozenset(
    {
        "models.github.ai",
        "models.inference.ai.azure.com",
        "api.githubcopilot.com",
        "models.github.com",
    }
)
FORBIDDEN_MODEL_MARKERS = frozenset({"gpt-5.6-luna", "gpt-5.6-terra"})

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
FACADE_MODEL_NAME = "contextual-orchestrator"

FetchFn = Callable[[str, dict[str, str], float], Any]


@dataclass(frozen=True)
class ProviderProfile:
    """One org upstream used for default discovery + fallback."""

    credential_name: str
    provider_name: str
    base_url: str
    fallback_models: tuple[str, ...]
    tags: tuple[str, ...] = ("reasoning", "writing", "coding", "review")
    priority: int = 1


# Fallback rows are the claim boundary when GET /v1/models fails — not a
# production seed that replaces discovery (#642 owns that seed).
ORG_PROVIDER_PROFILES: tuple[ProviderProfile, ...] = (
    ProviderProfile(
        credential_name="NVIDIA_NIM_API_KEY",
        provider_name="nvidia_nim",
        base_url="https://integrate.api.nvidia.com/v1",
        fallback_models=("moonshotai/kimi-k2.5",),
        tags=("reasoning", "coding", "writing"),
        priority=3,
    ),
    ProviderProfile(
        credential_name="NVIDIA_NIM_API_KEY_SUB",
        provider_name="nvidia_nim_sub",
        base_url="https://integrate.api.nvidia.com/v1",
        fallback_models=("nvidia/llama-3.3-nemotron-super-49b-v1",),
        tags=("reasoning", "coding"),
        priority=2,
    ),
    ProviderProfile(
        credential_name="OPENAI_API_KEY",
        provider_name="openai",
        base_url="https://api.openai.com/v1",
        fallback_models=("gpt-4o-mini",),
        tags=("reasoning", "writing", "coding"),
        priority=2,
    ),
    ProviderProfile(
        credential_name="OPENROUTER_API_KEY",
        provider_name="openrouter",
        base_url="https://openrouter.ai/api/v1",
        fallback_models=("openrouter/auto",),
        tags=("reasoning", "writing"),
        priority=1,
    ),
    ProviderProfile(
        credential_name="BYTEZ_API_KEY",
        provider_name="bytez",
        base_url="https://api.bytez.com/models/v2/openai/v1",
        fallback_models=("llama-3.1-8b-instruct",),
        tags=("reasoning", "writing"),
        priority=1,
    ),
)


@dataclass
class ProviderReport:
    """Per-provider compose outcome (no secrets)."""

    credential_name: str
    provider_name: str
    discovery_source: str
    model_count: int
    error_text: str = ""

    def as_dict(self) -> dict[str, Any]:
        """Serialize the report for CLI / tests (secret-free)."""
        return {
            "credential_name": self.credential_name,
            "provider_name": self.provider_name,
            "discovery_source": self.discovery_source,
            "model_count": self.model_count,
            "error_text": self.error_text,
        }


@dataclass
class ComposedCatalog:
    """Ready agents plus secret-free per-provider reports."""

    agents: list[ModelAgent] = field(default_factory=list)
    provider_reports: list[ProviderReport] = field(default_factory=list)


def _hostname_is_marker(host: str, marker: str) -> bool:
    """True when ``host`` is ``marker`` or a subdomain of it (not a substring)."""
    return host == marker or host.endswith("." + marker)


def catalog_allows_fields(base_url: str, model: str, credential_name: str) -> bool:
    """Return True when a row is not a retired GitHub Models / Copilot target."""
    if (credential_name or "") in FORBIDDEN_CREDENTIAL_NAMES:
        return False
    host = (urlparse(base_url).hostname or "").lower()
    if any(_hostname_is_marker(host, marker) for marker in FORBIDDEN_HOST_MARKERS):
        return False
    lowered_model = (model or "").lower()
    if any(marker == lowered_model or lowered_model.endswith("/" + marker) for marker in FORBIDDEN_MODEL_MARKERS):
        return False
    return True


def present_org_credentials() -> tuple[str, ...]:
    """Return org credential names that currently resolve from the KV."""
    present = []
    for name in ORG_CREDENTIAL_NAMES:
        if name in FORBIDDEN_CREDENTIAL_NAMES:
            continue
        if get_credential(name):
            present.append(name)
    return tuple(present)


def parse_models_list(payload: Any) -> list[str]:
    """Extract chat model ids from an OpenAI-shaped ``/v1/models`` payload.

    Malformed bodies return an empty list so the static fallback stays in
    force. Embedding/audio/image ids and retired GitHub Models names are
    dropped. Never raises on shape errors.
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


def default_models_fetch(url: str, headers: dict[str, str], timeout: float) -> Any:
    """FetchFn placeholder: production discover uses ``catalog_models_via_client``."""
    del url, headers, timeout
    raise RuntimeError("catalog fetch must go through ModelClient")


def catalog_models_via_client(base_url: str, credential_name: str, timeout: float) -> Any:
    """GET ``{base_url}/models`` through the existing chat egress stack."""
    agent = ModelAgent(
        id="catalog_discovery",
        model="catalog_probe",
        base_url=base_url,
        credential_key=credential_name,
    )
    return ModelClient(timeout=max(1, int(timeout))).fetch_provider_json(agent, "/models")


def discover_provider_models(
    base_url: str,
    credential_name: str,
    *,
    fetch: FetchFn | None = None,
    allow_insecure: bool = False,
    timeout: float = 10.0,
) -> list[str]:
    """GET ``{base_url}/models`` with the KV credential; return chat model ids.

    Any missing credential, transport, HTTP, or parse failure returns ``[]``
    so the caller can apply the static fallback. Discovery is the default
    path — there is no flag to opt in.

    The destination is rejected with ``provider_base_url_rejection`` **before**
    the KV credential is read or a Bearer header is built. ``allow_insecure``
    does not weaken that check (it is kept only so callers do not grow a
    second HTTP stack). Production fetch reuses ``ModelClient``.
    """
    del allow_insecure
    if credential_name in FORBIDDEN_CREDENTIAL_NAMES:
        return []
    if not catalog_allows_fields(base_url, "", credential_name):
        return []
    # Injected fetchers stay offline (no DNS). Literal loopback / link-local /
    # private IPs and non-HTTPS schemes still fail closed before the key is read.
    if provider_base_url_rejection(
        base_url,
        allowed_hosts=allowed_provider_hosts(),
        resolve_dns=fetch is None,
    ):
        return []
    try:
        if fetch is not None:
            api_key = get_credential(credential_name)
            if not api_key:
                return []
            payload = fetch(
                f"{base_url.rstrip('/')}/models",
                {"authorization": f"Bearer {api_key}", "accept": "application/json"},
                timeout,
            )
        else:
            payload = catalog_models_via_client(base_url, credential_name, timeout)
    except Exception:  # noqa: BLE001 - discovery must never break compose
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
    require_object_name(candidate, "agent.id")
    return candidate


def compose_default_catalog(
    *,
    fetch: FetchFn | None = None,
    allow_insecure: bool = False,
    profiles: Iterable[ProviderProfile] | None = None,
) -> ComposedCatalog:
    """Discover models for every present org credential; fall back per provider.

    Discovery is the default whenever a credential resolves from the KV. A
    static fallback is used only when ``GET /v1/models`` returns nothing.
    Missing credentials skip that upstream. Exceptions never escape.
    """
    catalog = ComposedCatalog()
    existing_ids: set[str] = set()
    seen_models: set[tuple[str, str]] = set()
    for profile in profiles or ORG_PROVIDER_PROFILES:
        if profile.credential_name in FORBIDDEN_CREDENTIAL_NAMES:
            catalog.provider_reports.append(
                ProviderReport(
                    profile.credential_name,
                    profile.provider_name,
                    "rejected",
                    0,
                    "forbidden_credential",
                )
            )
            continue
        if not catalog_allows_fields(profile.base_url, "", profile.credential_name):
            catalog.provider_reports.append(
                ProviderReport(
                    profile.credential_name,
                    profile.provider_name,
                    "rejected",
                    0,
                    "forbidden_provider",
                )
            )
            continue
        if not get_credential(profile.credential_name):
            catalog.provider_reports.append(
                ProviderReport(profile.credential_name, profile.provider_name, "skipped", 0, "credential_missing")
            )
            continue
        error_text = ""
        models: list[str] = []
        source = "discovered"
        try:
            models = discover_provider_models(
                profile.base_url,
                profile.credential_name,
                fetch=fetch,
                allow_insecure=allow_insecure,
            )
        except Exception as exc:  # noqa: BLE001 - compose stays up
            error_text = type(exc).__name__
            models = []
        if not models:
            models = list(profile.fallback_models)
            source = "fallback"
        added = 0
        for model in models:
            if not catalog_allows_fields(profile.base_url, model, profile.credential_name):
                continue
            key = (profile.base_url, model)
            if key in seen_models:
                continue
            agent_id = _discovered_agent_id(profile.provider_name, model, existing_ids)
            catalog.agents.append(
                ModelAgent(
                    id=agent_id,
                    model=model,
                    base_url=profile.base_url,
                    credential_key=profile.credential_name,
                    tags=profile.tags,
                    priority=profile.priority,
                    provider_name=profile.provider_name,
                )
            )
            existing_ids.add(agent_id)
            seen_models.add(key)
            added += 1
        catalog.provider_reports.append(
            ProviderReport(profile.credential_name, profile.provider_name, source, added, error_text)
        )
    return catalog


def merge_agent_pools(existing: list[ModelAgent], discovered: list[ModelAgent]) -> list[ModelAgent]:
    """Append discovered agents whose ``(base_url, model)`` is not already present."""
    seen = {(agent.base_url, agent.model) for agent in existing}
    merged = list(existing)
    existing_ids = {agent.id for agent in existing}
    for agent in discovered:
        if (agent.base_url, agent.model) in seen:
            continue
        if agent.id in existing_ids:
            agent_id = _discovered_agent_id(agent.provider_name, agent.model, existing_ids)
            agent = ModelAgent(
                id=agent_id,
                model=agent.model,
                base_url=agent.base_url,
                api_key_env=agent.api_key_env,
                credential_key=agent.credential_key,
                tags=agent.tags,
                priority=agent.priority,
                disabled=agent.disabled,
                provider_name=agent.provider_name,
                provider_exclusions=agent.provider_exclusions,
            )
        merged.append(agent)
        existing_ids.add(agent.id)
        seen.add((agent.base_url, agent.model))
    return merged


def models_list_payload(
    agents: Iterable[Any],
    *,
    facade_model: str = FACADE_MODEL_NAME,
    created_at: int = 0,
) -> dict[str, Any]:
    """OpenAI-shaped ``GET /v1/models`` body for this gateway's composed catalog."""
    data: list[dict[str, Any]] = [
        {
            "id": facade_model,
            "object": "model",
            "created": created_at,
            "owned_by": "contextual-orchestrator",
        }
    ]
    seen = {facade_model}
    for agent in agents:
        model = getattr(agent, "model", "")
        if not model or model in seen:
            continue
        if not catalog_allows_fields(getattr(agent, "base_url", ""), model, getattr(agent, "credential_name", "")):
            continue
        seen.add(model)
        data.append(
            {
                "id": model,
                "object": "model",
                "created": created_at,
                "owned_by": getattr(agent, "provider_name", "") or "contextual-orchestrator",
            }
        )
    return {"object": "list", "data": data}
