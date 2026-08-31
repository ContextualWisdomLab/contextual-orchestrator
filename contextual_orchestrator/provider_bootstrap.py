"""Durable bootstrap for the organization provider credential inventory.

A trusted deployment process may expose the provider-secret inventory declared
this one-shot module. Values are validated as a complete set, written to the
configured credential KV, and then model discovery runs exclusively through the
KV-backed runtime seam. Runtime provider calls never read provider API keys from
``os.environ``.

Bootstrap establishes a conservative serving candidate set. It does not infer
reasoning, coding, vision, or other provider capabilities from model names;
capability negotiation remains an explicit runtime/catalog responsibility.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
import json
import os
from typing import Mapping, Sequence

from .cost_ledger import PriceBook
from .credentials import (
    InMemoryCredentialBackend,
    PostgresCredentialBackend,
    get_backend,
)
from .kv_config import InMemoryConfigStore
from .model_discovery import (
    DiscoveredModel,
    PROVIDER_MODEL_SOURCES,
    _currency_is_comparable,
    agent_from_discovered,
    agent_id_for,
    discover_all_models,
    privacy_tags_for_discovered,
    is_routable_discovered_model,
    model_group_name_for,
    refresh_price_book,
)
from .orchestrator import ModelAgent, TaskOrchestrator


PROVIDER_CREDENTIAL_NAMES: tuple[str, ...] = tuple(
    dict.fromkeys(
        source.credential_name
        for source in PROVIDER_MODEL_SOURCES
        if source.bootstrap_required
    )
)
"""Required credential inventory derived from provider source declarations."""

PROVIDER_ACCEPTED_CREDENTIAL_NAMES: tuple[str, ...] = tuple(
    dict.fromkeys(source.credential_name for source in PROVIDER_MODEL_SOURCES)
)
"""All accepted credentials, including optional provider integrations."""

_GENERIC_SERVING_TAGS = (
    "discovered",
    "chat",
    "worker",
    "writing",
    "synthesizer",
)


class ProviderBootstrapError(RuntimeError):
    """Raised when trusted provider bootstrap cannot establish a usable catalog."""


@dataclass(frozen=True)
class ProviderBootstrapReport:
    """Secret-free evidence emitted after one provider bootstrap run."""

    registered_credentials: tuple[str, ...]
    discovered_model_count: int
    eligible_model_count: int
    selected_agent_ids: tuple[str, ...]
    enabled_agent_ids: tuple[str, ...]
    durable_agent_pool: bool
    providers_with_errors: tuple[str, ...]
    priced_model_count: int

    def as_dict(self) -> dict[str, object]:
        """Return JSON-safe evidence without credential values or provider payloads."""
        return {
            "registered_credentials": list(self.registered_credentials),
            "discovered_model_count": self.discovered_model_count,
            "eligible_model_count": self.eligible_model_count,
            "selected_agent_ids": list(self.selected_agent_ids),
            "enabled_agent_ids": list(self.enabled_agent_ids),
            "durable_agent_pool": self.durable_agent_pool,
            "providers_with_errors": list(self.providers_with_errors),
            "priced_model_count": self.priced_model_count,
        }


def _strip_mounted_line_endings(value: str) -> str:
    """Remove only CR/LF bytes commonly appended by mounted secret files."""
    return value.rstrip("\r\n")


def collect_provider_credentials(
    environ: Mapping[str, str], *, require_all: bool = True
) -> dict[str, str]:
    """Collect the declared inventory without rewriting non-line-ending bytes."""
    values: dict[str, str] = {}
    missing: list[str] = []
    for name in PROVIDER_ACCEPTED_CREDENTIAL_NAMES:
        raw = environ.get(name, "")
        value = _strip_mounted_line_endings(raw) if isinstance(raw, str) else ""
        if value and value.strip():
            values[name] = value
        elif name in PROVIDER_CREDENTIAL_NAMES:
            missing.append(name)
    if require_all and missing:
        raise ProviderBootstrapError(
            "provider bootstrap requires the complete credential inventory: "
            + ", ".join(sorted(missing))
        )
    if not values:
        raise ProviderBootstrapError("provider bootstrap received no credentials")
    return values


def register_provider_credentials_atomically(
    credentials: Mapping[str, str],
) -> tuple[str, ...]:
    """Register a validated credential batch with one commit where supported."""
    if not credentials:
        raise ProviderBootstrapError("provider bootstrap received an empty credential batch")
    unknown = sorted(set(credentials) - set(PROVIDER_ACCEPTED_CREDENTIAL_NAMES))
    if unknown:
        raise ProviderBootstrapError("provider bootstrap rejected unknown credential names")

    normalized: dict[str, str] = {}
    for name, value in credentials.items():
        if not isinstance(value, str):
            raise ProviderBootstrapError(
                f"provider bootstrap rejected an empty value for {name}"
            )
        normalized_value = _strip_mounted_line_endings(value)
        if not normalized_value or not normalized_value.strip():
            raise ProviderBootstrapError(
                f"provider bootstrap rejected an empty value for {name}"
            )
        normalized[name] = normalized_value

    backend = get_backend()
    if isinstance(backend, InMemoryCredentialBackend):
        with backend._lock:  # noqa: SLF001 - package-internal atomic batch operation
            backend._store.update(normalized)  # noqa: SLF001
    elif isinstance(backend, PostgresCredentialBackend):
        with backend._connect() as connection:  # noqa: SLF001 - package transaction
            backend._ensure_schema(connection)  # noqa: SLF001
            with connection.cursor() as cursor:
                for name, value in normalized.items():
                    cursor.execute(
                        "INSERT INTO provider_credentials "
                        "(credential_name, encrypted_value, updated_at) "
                        "VALUES (%s, pgp_sym_encrypt(%s, %s), now()) "
                        "ON CONFLICT (credential_name) DO UPDATE SET "
                        "encrypted_value = EXCLUDED.encrypted_value, updated_at = now()",
                        (name, value, backend._passphrase),  # noqa: SLF001
                    )
            connection.commit()
    else:
        raise ProviderBootstrapError(
            "provider bootstrap requires an atomic built-in credential backend"
        )
    return tuple(sorted(normalized))


def is_chat_serving_candidate(model: DiscoveredModel) -> bool:
    """Apply the shared ordinary-chat eligibility policy to a catalog row.

    This is a negative compatibility filter, not positive capability inference.
    Models that survive retain only explicit provider/catalog capability and
    cost evidence in addition to the generic chat-serving tags.
    """
    return is_routable_discovered_model(model)


def serving_tags_for_discovered(model: DiscoveredModel) -> tuple[str, ...]:
    """Return only provider-declared capabilities, modalities, and cost evidence."""
    return tuple(
        dict.fromkeys(
            (
                *_GENERIC_SERVING_TAGS,
                *(("cost:free",) if model.is_free else ()),
                *(("spend:blocked",) if not model.spend_admitted else ()),
                *privacy_tags_for_discovered(model),
                *model.capabilities,
                *(f"capability:{value}" for value in model.capabilities),
                *(f"input:{value}" for value in model.input_modalities),
                *(f"output:{value}" for value in model.output_modalities),
            )
        )
    )


def _known_cost_sort_key(
    model: DiscoveredModel,
) -> tuple[int, float, str, str]:
    """Sort known-price, comparable-currency models before unknown/incomparable ones.

    Mirrors ``model_discovery._discovery_price_key``'s currency gate so a
    cheap non-USD price can never outrank a USD one on face value alone.
    """
    prices = (model.prompt_price_per_1k, model.completion_price_per_1k)
    prompt_price, completion_price = prices
    if (
        prompt_price is None
        or completion_price is None
        or not _currency_is_comparable(model.currency_code, "USD")
    ):
        return (1, float("inf"), model.provider_name, model.model_id)
    return (0, prompt_price + completion_price, model.provider_name, model.model_id)


def select_model_group_diverse_models(
    discovered: Sequence[DiscoveredModel], *, limit: int
) -> list[DiscoveredModel]:
    """Choose a bounded compatible pool with one first-pass endpoint per model group."""
    if limit < 1:
        raise ValueError("provider bootstrap model limit must be positive")
    unique: dict[tuple[str, str, str], DiscoveredModel] = {}
    for model in discovered:
        if not is_chat_serving_candidate(model):
            continue
        unique[(model.provider_name, model.credential_name, model.model_id)] = model
    ordered = sorted(unique.values(), key=_known_cost_sort_key)
    selected: list[DiscoveredModel] = []
    seen_model_groups: set[str] = set()
    for model in ordered:
        model_group = model_group_name_for(model)
        if model_group in seen_model_groups:
            continue
        selected.append(model)
        seen_model_groups.add(model_group)
        if len(selected) >= limit:
            return selected
    selected_keys = {
        (item.provider_name, item.credential_name, item.model_id)
        for item in selected
    }
    for model in ordered:
        key = (model.provider_name, model.credential_name, model.model_id)
        if key in selected_keys:
            continue
        selected.append(model)
        if len(selected) >= limit:
            break
    return selected


def _active_agent_from_discovered(model: DiscoveredModel) -> ModelAgent:
    """Convert one selected chat model into an enabled capability-neutral agent."""
    return replace(
        agent_from_discovered(model),
        disabled=False,
        tags=serving_tags_for_discovered(model),
    )


def _synchronize_durable_agent_pool(
    agents_db: str,
    selected: Sequence[DiscoveredModel],
) -> tuple[str, ...]:
    """Activate exactly the selected discovered models in one durable agent pool."""
    agents = [_active_agent_from_discovered(model) for model in selected]
    bootstrap = TaskOrchestrator(
        agents,
        agents_db=agents_db,
        allow_empty_agents=True,
    )
    try:
        selected_ids = {agent.id for agent in agents}
        bootstrap.sync_discovered_agents(agents)
        selected_ids = {
            candidate.id
            for candidate in bootstrap.candidates
            if any(
                candidate.provider_name == agent.provider_name
                and candidate.credential_name == agent.credential_name
                and candidate.model == agent.model
                for agent in agents
            )
        }

        for candidate in list(bootstrap.candidates):
            if candidate.id in selected_ids:
                continue
            if "discovered" in candidate.tags:
                if not candidate.disabled:
                    bootstrap.remove_agent("default", candidate.id)

        for agent_id in selected_ids:
            bootstrap.patch_agent("default", agent_id, {"status": "active"})

        # The patch loop above raises KeyError if any selected agent is missing from
        # the pool, so the enabled set equals selected_ids by construction here.
        return tuple(
            sorted(agent.id for agent in bootstrap.agents if agent.id in selected_ids)
        )
    finally:
        bootstrap.close()


def bootstrap_provider_runtime(
    *,
    environ: Mapping[str, str],
    require_all_credentials: bool = True,
    agents_db: str | None = None,
    model_limit: int = 16,
) -> ProviderBootstrapReport:
    """Register trusted secrets, discover chat models, and optionally activate a pool."""
    credentials = collect_provider_credentials(
        environ, require_all=require_all_credentials
    )
    registered = register_provider_credentials_atomically(credentials)
    discovered, errors = discover_all_models()
    if not discovered:
        raise ProviderBootstrapError(
            "provider bootstrap discovered no usable models"
        )

    eligible = [model for model in discovered if is_chat_serving_candidate(model)]
    if not eligible:
        raise ProviderBootstrapError(
            "provider bootstrap discovered no chat-capable models"
        )

    price_book = PriceBook(InMemoryConfigStore())
    priced_count = refresh_price_book(discovered, price_book)
    # select_model_group_diverse_models returns at least one model for a non-empty
    # input with a positive limit and raises ValueError for a non-positive one,
    # so the selection here is never empty.
    selected = select_model_group_diverse_models(eligible, limit=model_limit)
    selected_ids = tuple(agent_id_for(model) for model in selected)
    enabled_ids = (
        _synchronize_durable_agent_pool(agents_db, selected)
        if agents_db
        else ()
    )

    return ProviderBootstrapReport(
        registered_credentials=registered,
        discovered_model_count=len(discovered),
        eligible_model_count=len(eligible),
        selected_agent_ids=selected_ids,
        enabled_agent_ids=enabled_ids,
        durable_agent_pool=bool(agents_db),
        providers_with_errors=tuple(
            sorted({error.provider_name for error in errors})
        ),
        priced_model_count=priced_count,
    )


def main(argv: Sequence[str] | None = None) -> None:
    """Run the one-shot provider bootstrap command used by trusted deployment jobs."""
    parser = argparse.ArgumentParser(
        description="Register provider secrets and refresh the runtime model pool."
    )
    parser.add_argument(
        "--agents-db",
        default=os.environ.get("CONTEXTUAL_ORCHESTRATOR_AGENTS_DB") or None,
    )
    parser.add_argument("--model-limit", type=int, default=16)
    parser.add_argument(
        "--allow-partial-credentials",
        action="store_true",
        help="Permit a subset of the declared provider inventory (development only).",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    report = bootstrap_provider_runtime(
        environ=os.environ,
        require_all_credentials=not args.allow_partial_credentials,
        agents_db=args.agents_db,
        model_limit=args.model_limit,
    )
    print(json.dumps(report.as_dict(), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":  # pragma: no cover - subprocess/CLI coverage
    main()
