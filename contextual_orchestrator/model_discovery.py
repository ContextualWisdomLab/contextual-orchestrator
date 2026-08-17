"""Live model auto-discovery for the org LLM gateway.

This is the product catalog: ContextualWisdomLab apps consume whatever the
gateway discovers from registered provider credentials, then route with
Fugu (single-worker latency), Conductor (access-listed workflow), and
TRINITY (thinker / worker / verifier) compute allocation.

The two NVIDIA NIM ids in :data:`FLOOR_DEFAULT_MODEL_ID` and
:data:`FLOOR_SMALL_MODEL_ID` are a **floor only**. They are used when every
registered catalog fetch returns nothing. They are not the authoritative
inventory.

Credential resolution uses :func:`get_credential` only. A missing
registration is ``None`` — never ``os.getenv`` as a product fallback.

Price honesty (issue #86):

* an explicit billed rate of ``0`` is known-free;
* a free channel that still has a published list/sibling price stores that
  value as ``original_list_price`` and is compared at the list price;
* missing, boolean, non-numeric, negative, NaN, or infinite prices are
  ``unknown`` and are never converted to ``0`` / "free".
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import urlparse
import urllib.error
import urllib.request

from .conventions import is_two_word_snake_case, require_object_name
from .credentials import get_credential
from .orchestrator import ModelAgent, ModelClient, TaskOrchestrator


DISCOVERY_CREDENTIAL_NAMES: tuple[str, ...] = (
    "NVIDIA_NIM_API_KEY",
    "NVIDIA_NIM_API_KEY_SUB",
    "BYTEZ_API_KEY",
    "OPENROUTER_API_KEY",
    "OPENAI_API_KEY",
)

FLOOR_DEFAULT_MODEL_ID = "nvidia-nim/nvidia/nemotron-3-ultra-550b-a55b"
FLOOR_SMALL_MODEL_ID = "nvidia-nim/nvidia/nemotron-3-super-120b-a12b"

NVIDIA_NIM_BASE_URL = "https://integrate.api.nvidia.com/v1"
OPENAI_BASE_URL = "https://api.openai.com/v1"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
BYTEZ_BASE_URL = "https://api.bytez.com"

_NON_CHAT_MARKERS = (
    "embed",
    "rerank",
    "whisper",
    "tts",
    "dall-e",
    "dalle",
    "imagen",
    "moderation",
    "audio",
    "speech",
    "transcri",
    "image",
    "video",
    "clip",
)

_SMALL_MARKERS = (
    "mini",
    "small",
    "nano",
    "haiku",
    "flash",
    "super",
    "7b",
    "8b",
    "9b",
    "12b",
    "13b",
    "120b",
)
_LARGE_MARKERS = (
    "ultra",
    "opus",
    "sonnet",
    "o1",
    "o3",
    "o4",
    "gpt-4",
    "gpt-5",
    "70b",
    "72b",
    "405b",
    "550b",
)

_MAX_CATALOG_BYTES = 2 * 1024 * 1024
_AGENT_ID_MAX = 64

CatalogFetcher = Callable[["ProviderEndpoint", str], Any]


@dataclass(frozen=True)
class ProviderEndpoint:
    """One official catalog origin keyed by a KV credential name."""

    credential_name: str
    provider_name: str
    base_url: str
    catalog_path: str
    catalog_style: str
    auth_scheme: str
    price_unit: str
    http_method: str = "GET"


PROVIDER_ENDPOINTS: dict[str, ProviderEndpoint] = {
    "NVIDIA_NIM_API_KEY": ProviderEndpoint(
        credential_name="NVIDIA_NIM_API_KEY",
        provider_name="nvidia_nim",
        base_url=NVIDIA_NIM_BASE_URL,
        catalog_path="/models",
        catalog_style="openai",
        auth_scheme="bearer",
        price_unit="per_million",
    ),
    "NVIDIA_NIM_API_KEY_SUB": ProviderEndpoint(
        credential_name="NVIDIA_NIM_API_KEY_SUB",
        provider_name="nvidia_nim_sub",
        base_url=NVIDIA_NIM_BASE_URL,
        catalog_path="/models",
        catalog_style="openai",
        auth_scheme="bearer",
        price_unit="per_million",
    ),
    "BYTEZ_API_KEY": ProviderEndpoint(
        credential_name="BYTEZ_API_KEY",
        provider_name="bytez",
        base_url=BYTEZ_BASE_URL,
        catalog_path="/models/v2",
        catalog_style="bytez",
        auth_scheme="key",
        price_unit="per_million",
        http_method="GET",
    ),
    "OPENROUTER_API_KEY": ProviderEndpoint(
        credential_name="OPENROUTER_API_KEY",
        provider_name="openrouter",
        base_url=OPENROUTER_BASE_URL,
        catalog_path="/models",
        catalog_style="openai",
        auth_scheme="bearer",
        price_unit="per_token",
    ),
    "OPENAI_API_KEY": ProviderEndpoint(
        credential_name="OPENAI_API_KEY",
        provider_name="openai",
        base_url=OPENAI_BASE_URL,
        catalog_path="/models",
        catalog_style="openai",
        auth_scheme="bearer",
        price_unit="per_million",
    ),
}


@dataclass(frozen=True)
class CatalogModel:
    """One discovered (or floor) chat model with honest price fields."""

    model_id: str
    provider_name: str
    credential_name: str
    base_url: str
    owner: str = ""
    billed_prompt_per_million: float | None = None
    billed_completion_per_million: float | None = None
    original_list_prompt_per_million: float | None = None
    original_list_completion_per_million: float | None = None
    price_status: str = "unknown"
    discovery_source: str = "live"
    capability_kind: str = "chat"

    def comparison_cost(self) -> float | None:
        """Return the known ranking cost, or ``None`` when the model is unpriced.

        Promotional-free rows with a stored list price compare at that list
        price. Explicit billed ``0`` with no list price is known-free (``0``).
        Unknown is never converted to ``0``.
        """
        billed = _mean_known(
            self.billed_prompt_per_million, self.billed_completion_per_million
        )
        listed = _mean_known(
            self.original_list_prompt_per_million,
            self.original_list_completion_per_million,
        )
        if billed == 0.0 and listed is not None:
            return listed
        if billed is not None:
            return billed
        if listed is not None:
            return listed
        return None

    def as_dict(self) -> dict[str, Any]:
        """Secret-free snapshot row for operators and CWL consumers."""
        return {
            "model_id": self.model_id,
            "provider_name": self.provider_name,
            "credential_name": self.credential_name,
            "base_url": self.base_url,
            "owner": self.owner,
            "billed_prompt_per_million": self.billed_prompt_per_million,
            "billed_completion_per_million": self.billed_completion_per_million,
            "original_list_prompt_per_million": self.original_list_prompt_per_million,
            "original_list_completion_per_million": self.original_list_completion_per_million,
            "price_status": self.price_status,
            "discovery_source": self.discovery_source,
            "capability_kind": self.capability_kind,
            "comparison_cost": self.comparison_cost(),
        }


@dataclass
class DiscoverySnapshot:
    """Redacted result of one catalog composition pass."""

    models: list[CatalogModel]
    source: str
    used_floor: bool
    registered_credentials: tuple[str, ...]
    skipped_credentials: tuple[str, ...]
    provider_errors: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """Serialize the snapshot without secrets or raw provider payloads."""
        return {
            "source": self.source,
            "used_floor": self.used_floor,
            "registered_credentials": list(self.registered_credentials),
            "skipped_credentials": list(self.skipped_credentials),
            "provider_errors": dict(self.provider_errors),
            "model_count": len(self.models),
            "models": [model.as_dict() for model in self.models],
        }


def registered_discovery_keys() -> tuple[str, ...]:
    """Return discovery credential names that are present in the KV.

    Absence is ``get_credential(...) is None``. This function never reads
    ``os.getenv`` for a missing registration.
    """
    return tuple(name for name in DISCOVERY_CREDENTIAL_NAMES if get_credential(name))


def skipped_discovery_keys() -> tuple[str, ...]:
    """Return discovery names that have no KV registration (not an env miss)."""
    registered = set(registered_discovery_keys())
    return tuple(name for name in DISCOVERY_CREDENTIAL_NAMES if name not in registered)


def finite_unit_price(value: Any) -> float | None:
    """Parse a price as a finite non-negative float, or ``None`` if unknown.

    Booleans, strings that are not numbers, negatives, NaN, and infinities
    are unknown — they are not coerced to ``0``.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        stripped = value.strip()
        if stripped == "":
            return None
        value = stripped
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed != parsed or parsed in (float("inf"), float("-inf")) or parsed < 0:
        return None
    return parsed


def price_per_million(value: Any, *, unit: str) -> float | None:
    """Normalize a provider price into USD per million tokens, or unknown."""
    parsed = finite_unit_price(value)
    if parsed is None:
        return None
    if unit == "per_token":
        return parsed * 1_000_000.0
    return parsed


def classify_price_status(
    billed_prompt: float | None,
    billed_completion: float | None,
    list_prompt: float | None,
    list_completion: float | None,
) -> str:
    """Return ``known``, ``promotional_free``, or ``unknown``."""
    billed = _mean_known(billed_prompt, billed_completion)
    listed = _mean_known(list_prompt, list_completion)
    if billed == 0.0 and listed is not None:
        return "promotional_free"
    if billed is not None:
        return "known"
    if listed is not None:
        return "known"
    return "unknown"


def is_chat_model_id(model_id: str) -> bool:
    """Return whether ``model_id`` looks like a chat/completion candidate."""
    lowered = model_id.lower()
    return not any(marker in lowered for marker in _NON_CHAT_MARKERS)


def size_class_for_model(model_id: str) -> str:
    """Heuristic Fugu size class: ``small`` (latency) or ``default`` (quality)."""
    lowered = model_id.lower()
    if any(marker in lowered for marker in _LARGE_MARKERS):
        return "default"
    if any(marker in lowered for marker in _SMALL_MARKERS):
        return "small"
    return "default"


def allocate_compute_tags(model_id: str, *, size_class: str | None = None) -> tuple[str, ...]:
    """Assign Fugu / Conductor / TRINITY role tags from the model identity.

    Fugu latency routing prefers ``small`` / ``cheap`` workers. Conductor and
    TRINITY conduct paths need thinker (reasoning/planning), worker (coding),
    verifier (review), and synthesizer (writing) coverage. Tags are additive
    so a discovered model can fill more than one role when the pool is thin.
    """
    size = size_class or size_class_for_model(model_id)
    lowered = model_id.lower()
    tags = {"reasoning"}
    if size == "small":
        tags.update({"cheap", "fallback", "coding", "implementation", "summarization"})
    else:
        tags.update({"planning", "writing", "analysis", "review", "verification"})
    if any(token in lowered for token in ("code", "coder", "codex", "starcoder", "qwen2.5-coder")):
        tags.update({"coding", "implementation", "debugging"})
    if any(token in lowered for token in ("guard", "safety", "review", "critic")):
        tags.update({"review", "verification", "security"})
    return tuple(sorted(tags))


def agent_id_for(provider_name: str, model_id: str, taken: set[str]) -> str:
    """Build a two-word snake_case agent id, resolving slug collisions."""
    raw = f"{provider_name}_{model_id}".lower()
    slug = re.sub(r"[^a-z0-9]+", "_", raw).strip("_")
    if not slug:
        slug = "discovered_model"
    if "_" not in slug:
        slug = f"model_{slug}"
    slug = slug[:_AGENT_ID_MAX].rstrip("_")
    if not is_two_word_snake_case(slug):
        slug = f"model_{slug}" if "_" not in slug else slug
        slug = re.sub(r"_+", "_", slug).strip("_")
    candidate = slug
    suffix = 2
    while candidate in taken or not is_two_word_snake_case(candidate):
        trimmed = slug[: max(8, _AGENT_ID_MAX - 3)]
        candidate = f"{trimmed}_{suffix}"
        suffix += 1
    require_object_name(candidate, "agent.id")
    taken.add(candidate)
    return candidate


def floor_models() -> list[CatalogModel]:
    """Return the two NIM floor rows used only when discovery is empty."""
    return [
        CatalogModel(
            model_id=FLOOR_DEFAULT_MODEL_ID,
            provider_name="nvidia_nim",
            credential_name="NVIDIA_NIM_API_KEY",
            base_url=NVIDIA_NIM_BASE_URL,
            owner="nvidia",
            price_status="unknown",
            discovery_source="floor",
        ),
        CatalogModel(
            model_id=FLOOR_SMALL_MODEL_ID,
            provider_name="nvidia_nim",
            credential_name="NVIDIA_NIM_API_KEY",
            base_url=NVIDIA_NIM_BASE_URL,
            owner="nvidia",
            price_status="unknown",
            discovery_source="floor",
        ),
    ]


def extract_catalog_rows(payload: Any) -> list[dict[str, Any]]:
    """Normalize an arbitrary catalog JSON payload into row mappings.

    Accepts OpenAI ``{data: [...]}``, Bytez ``{models: [...]}``, or a bare
    list. Non-mapping items and non-container payloads yield an empty list
    rather than inventing models.
    """
    if isinstance(payload, list):
        raw_rows = payload
    elif isinstance(payload, Mapping):
        for key in ("data", "models", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                raw_rows = value
                break
        else:
            return []
    else:
        return []
    rows: list[dict[str, Any]] = []
    for item in raw_rows:
        if isinstance(item, Mapping):
            rows.append(dict(item))
        elif isinstance(item, str) and item.strip():
            rows.append({"id": item.strip()})
    return rows


def row_model_id(row: Mapping[str, Any]) -> str:
    """Return the catalog model id from a provider row, or empty."""
    for key in ("id", "model", "name", "model_id"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def row_owner(row: Mapping[str, Any], model_id: str) -> str:
    """Best-effort owner/org label from a catalog row."""
    for key in ("owned_by", "owner", "organization", "publisher"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    if "/" in model_id:
        return model_id.split("/", 1)[0]
    return ""


def extract_row_prices(
    row: Mapping[str, Any], *, unit: str
) -> tuple[float | None, float | None, float | None, float | None]:
    """Return billed and original-list prompt/completion prices per million.

    List/published fields are preserved even when the billed channel is free.
    """
    pricing = row.get("pricing") if isinstance(row.get("pricing"), Mapping) else {}
    billed_prompt = _first_price(
        row,
        pricing,
        (
            "prompt_price_per_million",
            "input_price_per_million",
            "prompt",
            "input",
        ),
        unit=unit,
    )
    billed_completion = _first_price(
        row,
        pricing,
        (
            "completion_price_per_million",
            "output_price_per_million",
            "completion",
            "output",
        ),
        unit=unit,
    )
    list_prompt = _first_price(
        row,
        pricing,
        (
            "list_prompt_per_million",
            "published_prompt_per_million",
            "original_prompt_per_million",
            "list_prompt",
            "published_prompt",
            "original_list_prompt",
        ),
        unit=unit,
    )
    list_completion = _first_price(
        row,
        pricing,
        (
            "list_completion_per_million",
            "published_completion_per_million",
            "original_completion_per_million",
            "list_completion",
            "published_completion",
            "original_list_completion",
        ),
        unit=unit,
    )
    return billed_prompt, billed_completion, list_prompt, list_completion


def sibling_list_price(
    model_id: str,
    rows_by_id: Mapping[str, Mapping[str, Any]],
    *,
    unit: str,
) -> tuple[float | None, float | None]:
    """For a ``:free`` variant, copy the paid sibling's billed rates as list price."""
    if not model_id.endswith(":free"):
        return None, None
    sibling_id = model_id[: -len(":free")]
    sibling = rows_by_id.get(sibling_id)
    if sibling is None:
        return None, None
    prompt, completion, list_prompt, list_completion = extract_row_prices(sibling, unit=unit)
    return (
        list_prompt if list_prompt is not None else prompt,
        list_completion if list_completion is not None else completion,
    )


def normalize_catalog_payload(
    payload: Any,
    endpoint: ProviderEndpoint,
) -> list[CatalogModel]:
    """Turn one provider catalog payload into chat :class:`CatalogModel` rows.

    This is the untrusted-input seam: malformed or duplicate catalogs must
    not invent models, leak secrets, or treat junk prices as free.
    """
    rows = extract_catalog_rows(payload)
    rows_by_id = {row_model_id(row): row for row in rows if row_model_id(row)}
    seen: set[str] = set()
    models: list[CatalogModel] = []
    for row in rows:
        model_id = row_model_id(row)
        if not model_id or model_id in seen or not is_chat_model_id(model_id):
            continue
        seen.add(model_id)
        billed_prompt, billed_completion, list_prompt, list_completion = extract_row_prices(
            row, unit=endpoint.price_unit
        )
        sibling_prompt, sibling_completion = sibling_list_price(
            model_id, rows_by_id, unit=endpoint.price_unit
        )
        if list_prompt is None:
            list_prompt = sibling_prompt
        if list_completion is None:
            list_completion = sibling_completion
        status = classify_price_status(
            billed_prompt, billed_completion, list_prompt, list_completion
        )
        models.append(
            CatalogModel(
                model_id=model_id,
                provider_name=endpoint.provider_name,
                credential_name=endpoint.credential_name,
                base_url=endpoint.base_url,
                owner=row_owner(row, model_id),
                billed_prompt_per_million=billed_prompt,
                billed_completion_per_million=billed_completion,
                original_list_prompt_per_million=list_prompt,
                original_list_completion_per_million=list_completion,
                price_status=status,
                discovery_source="live",
            )
        )
    return models


def discover_model_catalog(
    *,
    fetcher: CatalogFetcher | None = None,
) -> DiscoverySnapshot:
    """Discover chat models from every KV-registered provider key.

    Unregistered names are skipped (KV miss, not an environment fallback).
    When every fetch is empty or fails, the snapshot is the NIM floor.
    """
    registered = registered_discovery_keys()
    skipped = skipped_discovery_keys()
    fetch = fetcher or fetch_provider_catalog
    discovered: list[CatalogModel] = []
    errors: dict[str, str] = {}
    for name in registered:
        endpoint = PROVIDER_ENDPOINTS[name]
        api_key = get_credential(name)
        if not api_key:
            continue
        try:
            payload = fetch(endpoint, api_key)
            discovered.extend(normalize_catalog_payload(payload, endpoint))
        except Exception as exc:  # noqa: BLE001 - one provider must not abort the catalog
            errors[name] = _redact_error(exc)
    if discovered:
        return DiscoverySnapshot(
            models=_dedupe_models(discovered),
            source="live",
            used_floor=False,
            registered_credentials=registered,
            skipped_credentials=skipped,
            provider_errors=errors,
        )
    return DiscoverySnapshot(
        models=floor_models(),
        source="floor",
        used_floor=True,
        registered_credentials=registered,
        skipped_credentials=skipped,
        provider_errors=errors,
    )


def agents_from_catalog(models: Iterable[CatalogModel]) -> list[ModelAgent]:
    """Materialize :class:`ModelAgent` workers from catalog rows."""
    taken: set[str] = set()
    agents: list[ModelAgent] = []
    for model in models:
        agent_id = agent_id_for(model.provider_name, model.model_id, taken)
        size = size_class_for_model(model.model_id)
        cost = model.comparison_cost()
        list_cost = _mean_known(
            model.original_list_prompt_per_million,
            model.original_list_completion_per_million,
        )
        agents.append(
            ModelAgent(
                id=agent_id,
                model=model.model_id,
                base_url=model.base_url,
                credential_key=model.credential_name,
                tags=allocate_compute_tags(model.model_id, size_class=size),
                priority=2 if size == "default" else 1,
                provider_name=model.provider_name,
                price_per_million=cost,
                original_list_price=list_cost,
                price_status=model.price_status,
                discovery_source=model.discovery_source,
            )
        )
    return agents


def apply_discovered_pool(
    orchestrator: TaskOrchestrator,
    *,
    fetcher: CatalogFetcher | None = None,
    replace_unregistered: bool = False,
) -> DiscoverySnapshot:
    """Replace the live pool when discovery credentials are registered.

    If no discovery key is in the KV, the seed/mock pool is left in place
    unless ``replace_unregistered`` is true (tests / explicit product floor).
    ``os.getenv`` is never consulted to decide that a key "exists".
    """
    fetch = fetcher or getattr(orchestrator, "catalog_fetcher", None)
    registered = registered_discovery_keys()
    if not registered and not replace_unregistered:
        snapshot = DiscoverySnapshot(
            models=[],
            source="seed",
            used_floor=False,
            registered_credentials=(),
            skipped_credentials=skipped_discovery_keys(),
        )
        orchestrator.discovery_snapshot = snapshot.as_dict()
        return snapshot
    snapshot = discover_model_catalog(fetcher=fetch)
    agents = agents_from_catalog(snapshot.models)
    if agents:
        orchestrator.agents = agents
    orchestrator.discovery_snapshot = snapshot.as_dict()
    return snapshot


def list_served_models(orchestrator: TaskOrchestrator) -> dict[str, Any]:
    """OpenAI-compatible ``GET /v1/models`` body for this gateway."""
    rows = [
        {
            "id": "contextual-orchestrator",
            "object": "model",
            "owned_by": "contextual-orchestrator",
            "discovery_source": "gateway",
        }
    ]
    seen = {"contextual-orchestrator"}
    for agent in orchestrator.agents:
        if agent.model in seen:
            continue
        seen.add(agent.model)
        rows.append(
            {
                "id": agent.model,
                "object": "model",
                "owned_by": agent.provider_name or "agent_pool",
                "discovery_source": agent.discovery_source or "seed",
                "price_status": agent.price_status,
                "original_list_price": agent.original_list_price,
            }
        )
    return {"object": "list", "data": rows}


def comparison_cost_for_agent(agent: ModelAgent) -> float | None:
    """Known ranking cost for a worker, or ``None`` when unpriced.

    A free billed channel with ``original_list_price`` compares at the list
    price. Unpriced agents are not treated as free.
    """
    listed = finite_unit_price(getattr(agent, "original_list_price", None))
    billed = finite_unit_price(getattr(agent, "price_per_million", None))
    status = getattr(agent, "price_status", "unknown")
    if status == "unknown" and billed is None and listed is None:
        return None
    if billed == 0.0 and listed is not None:
        return listed
    if billed is not None:
        return billed
    return listed


def fetch_provider_catalog(endpoint: ProviderEndpoint, api_key: str) -> Any:
    """Fetch one official catalog through the chat egress policy.

    Reuses :class:`ModelClient` host/TLS checks. Redirects are rejected.
    The Bearer/Key header is attached only after the URL is validated.
    """
    probe = ModelAgent(
        id="catalog_probe",
        model="catalog_probe",
        base_url=endpoint.base_url,
        credential_key=endpoint.credential_name,
        provider_name=endpoint.provider_name,
    )
    client = ModelClient(timeout=30)
    client._validate_provider(probe)
    url = client._provider_url(probe, endpoint.catalog_path)
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise RuntimeError("catalog URL must be https")
    authorization = (
        f"Key {api_key}" if endpoint.auth_scheme == "key" else f"Bearer {api_key}"
    )
    request = urllib.request.Request(
        url,
        headers={
            "authorization": authorization,
            "accept": "application/json",
        },
        method=endpoint.http_method,
    )
    opener = urllib.request.build_opener(
        _NoRedirectHandler,
        urllib.request.HTTPSHandler(context=client._ssl_context),
    )
    with opener.open(request, timeout=client.timeout) as response:  # nosec B310 - URL from validated provider origin.  # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
        raw = response.read(_MAX_CATALOG_BYTES + 1)
    if len(raw) > _MAX_CATALOG_BYTES:
        raise RuntimeError("catalog response exceeded bounded size")
    return json.loads(raw.decode("utf-8"))


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Fail closed when a catalog origin tries to redirect the KV Bearer."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        raise urllib.error.HTTPError(req.full_url, code, "catalog redirect rejected", headers, fp)


def _first_price(
    row: Mapping[str, Any],
    pricing: Mapping[str, Any],
    keys: tuple[str, ...],
    *,
    unit: str,
) -> float | None:
    for key in keys:
        if key in pricing:
            parsed = price_per_million(pricing.get(key), unit=unit)
            if parsed is not None:
                return parsed
        if key in row:
            parsed = price_per_million(row.get(key), unit=unit)
            if parsed is not None:
                return parsed
    return None


def _mean_known(*values: float | None) -> float | None:
    known = [value for value in values if value is not None]
    if not known:
        return None
    return sum(known) / len(known)


def _dedupe_models(models: list[CatalogModel]) -> list[CatalogModel]:
    seen: set[tuple[str, str]] = set()
    unique: list[CatalogModel] = []
    for model in models:
        key = (model.provider_name, model.model_id)
        if key in seen:
            continue
        seen.add(key)
        unique.append(model)
    return unique


def _redact_error(exc: BaseException) -> str:
    text = f"{type(exc).__name__}: {exc}"
    return re.sub(r"(?i)(bearer|key|sk-|nvapi-)[^\s]+", "[REDACTED]", text)
