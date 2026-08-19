"""Durable bootstrap for the organization provider credential inventory.

GitHub Actions or another trusted deployment process may expose the fixed provider
secret inventory to this one-shot module. Values are validated as a complete set,
written to the configured credential KV, and then model discovery runs exclusively
through the KV-backed runtime seam. Runtime provider calls never read these provider
API keys from ``os.environ``.

The bootstrap is deliberately package-owned rather than workflow-owned so the same
transaction and validation contract is reusable from Kubernetes Jobs, local release
scripts, and GitHub Actions.
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
    agent_from_discovered,
    agent_id_for,
    discover_all_models,
    refresh_price_book,
)
from .orchestrator import ModelAgent, TaskOrchestrator


PROVIDER_CREDENTIAL_NAMES: tuple[str, ...] = tuple(
    dict.fromkeys(source.credential_name for source in PROVIDER_MODEL_SOURCES)
)
"""Fixed organization credential inventory accepted by the bootstrap boundary."""


class ProviderBootstrapError(RuntimeError):
    """Raised when trusted provider bootstrap cannot establish a usable catalog."""


@dataclass(frozen=True)
class ProviderBootstrapReport:
    """Secret-free evidence emitted after one provider bootstrap run."""

    registered_credentials: tuple[str, ...]
    discovered_model_count: int
    enabled_agent_ids: tuple[str, ...]
    providers_with_errors: tuple[str, ...]
    priced_model_count: int

    def as_dict(self) -> dict[str, object]:
        """Return JSON-safe evidence without credential values or provider payloads."""
        return {
            "registered_credentials": list(self.registered_credentials),
            "discovered_model_count": self.discovered_model_count,
            "enabled_agent_ids": list(self.enabled_agent_ids),
            "providers_with_errors": list(self.providers_with_errors),
            "priced_model_count": self.priced_model_count,
        }


def collect_provider_credentials(
    environ: Mapping[str, str], *, require_all: bool = True
) -> dict[str, str]:
    """Collect the fixed secret inventory from a trusted bootstrap environment.

    Values are stripped before registration so mounted secrets ending in a newline
    remain usable. No credential value is included in an exception or report.
    """
    values: dict[str, str] = {}
    missing: list[str] = []
    for name in PROVIDER_CREDENTIAL_NAMES:
        raw = environ.get(name, "")
        value = raw.strip() if isinstance(raw, str) else ""
        if value:
            values[name] = value
        else:
            missing.append(name)
    if require_all and missing:
        raise ProviderBootstrapError(
            "provider bootstrap requires the complete credential inventory: "
            + ", ".join(sorted(missing))
        )
    if not values:
        raise ProviderBootstrapError("provider bootstrap received no credentials")
    return values


def register_provider_credentials_atomically(credentials: Mapping[str, str]) -> tuple[str, ...]:
    """Register a validated credential batch with one commit where supported.

    The package's built-in memory and PostgreSQL backends are handled atomically.
    Unknown custom backends are rejected instead of risking a partial multi-key write.
    """
    if not credentials:
        raise ProviderBootstrapError("provider bootstrap received an empty credential batch")
    unknown = sorted(set(credentials) - set(PROVIDER_CREDENTIAL_NAMES))
    if unknown:
        raise ProviderBootstrapError("provider bootstrap rejected unknown credential names")
    for name, value in credentials.items():
        if not isinstance(value, str) or not value.strip():
            raise ProviderBootstrapError(f"provider bootstrap rejected an empty value for {name}")

    backend = get_backend()
    normalized = {name: value.strip() for name, value in credentials.items()}
    if isinstance(backend, InMemoryCredentialBackend):
        # These fields are package-private implementation state. Keeping the update
        # under the backend's existing lock gives the dev/test backend the same
        # all-or-nothing visibility contract as PostgreSQL.
        with backend._lock:  # noqa: SLF001 - package-internal atomic batch operation
            backend._store.update(normalized)  # noqa: SLF001
    elif isinstance(backend, PostgresCredentialBackend):
        with backend._connect() as connection:  # noqa: SLF001 - package-internal transaction
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


def _known_cost_sort_key(model: DiscoveredModel) -> tuple[int, float, str, str]:
    """Sort known-price models before unknown-price models without inventing free cost."""
    prices = (model.prompt_price_per_1k, model.completion_price_per_1k)
    known = [price for price in prices if price is not None]
    if not known:
        return (1, float("inf"), model.provider_name, model.model_id)
    return (0, sum(known), model.provider_name, model.model_id)


def select_provider_diverse_models(
    discovered: Sequence[DiscoveredModel], *, limit: int
) -> list[DiscoveredModel]:
    """Choose a bounded pool while preserving provider/account diversity.

    The first pass selects the best known-cost candidate from every discovered
    provider account. Remaining slots are filled by the same honest cost ordering.
    Unknown price is never coerced to zero. Model quality/capability decisions remain
    the responsibility of the ordinary orchestrator routing policy after bootstrap.
    """
    if limit < 1:
        raise ValueError("provider bootstrap model limit must be positive")
    unique: dict[tuple[str, str, str], DiscoveredModel] = {}
    for model in discovered:
        unique[(model.provider_name, model.credential_name, model.model_id)] = model
    ordered = sorted(unique.values(), key=_known_cost_sort_key)
    selected: list[DiscoveredModel] = []
    seen_providers: set[str] = set()
    for model in ordered:
        if model.provider_name in seen_providers:
            continue
        selected.append(model)
        seen_providers.add(model.provider_name)
        if len(selected) >= limit:
            return selected
    selected_keys = {(item.provider_name, item.credential_name, item.model_id) for item in selected}
    for model in ordered:
        key = (model.provider_name, model.credential_name, model.model_id)
        if key in selected_keys:
            continue
        selected.append(model)
        if len(selected) >= limit:
            break
    return selected


def bootstrap_provider_runtime(
    *,
    environ: Mapping[str, str],
    require_all_credentials: bool = True,
    agents_db: str | None = None,
    model_limit: int = 16,
) -> ProviderBootstrapReport:
    """Register trusted secrets, discover models, and optionally activate a durable pool."""
    credentials = collect_provider_credentials(environ, require_all=require_all_credentials)
    registered = register_provider_credentials_atomically(credentials)
    discovered, errors = discover_all_models()
    if not discovered:
        raise ProviderBootstrapError("provider bootstrap discovered no usable models")

    price_book = PriceBook(InMemoryConfigStore())
    priced_count = refresh_price_book(discovered, price_book)
    selected = select_provider_diverse_models(discovered, limit=model_limit)
    enabled_ids: list[str] = []

    if agents_db:
        bootstrap = TaskOrchestrator(
            [ModelAgent("bootstrap_agent", "bootstrap-model")], agents_db=agents_db
        )
        agents = [replace(agent_from_discovered(model), disabled=False) for model in selected]
        bootstrap.sync_discovered_agents(agents)
        for agent in agents:
            # sync_discovered_agents may preserve a pre-existing disabled row. Make
            # the selected bounded pool explicitly active and leave all other rows
            # withdrawn by the sync operation.
            bootstrap.patch_agent("default", agent.id, {"status": "active"})
            enabled_ids.append(agent.id)
    else:
        enabled_ids.extend(agent_id_for(model) for model in selected)

    return ProviderBootstrapReport(
        registered_credentials=registered,
        discovered_model_count=len(discovered),
        enabled_agent_ids=tuple(enabled_ids),
        providers_with_errors=tuple(sorted({error.provider_name for error in errors})),
        priced_model_count=priced_count,
    )


def main(argv: Sequence[str] | None = None) -> None:
    """Run the one-shot provider bootstrap command used by trusted deployment jobs."""
    parser = argparse.ArgumentParser(description="Register provider secrets and refresh the runtime model pool.")
    parser.add_argument("--agents-db", default=os.environ.get("CONTEXTUAL_ORCHESTRATOR_AGENTS_DB") or None)
    parser.add_argument("--model-limit", type=int, default=16)
    parser.add_argument(
        "--allow-partial-credentials",
        action="store_true",
        help="Permit a subset of the fixed provider inventory (development only).",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    report = bootstrap_provider_runtime(
        environ=os.environ,
        require_all_credentials=not args.allow_partial_credentials,
        agents_db=args.agents_db,
        model_limit=args.model_limit,
    )
    print(json.dumps(report.as_dict(), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":  # pragma: no cover - exercised through subprocess/CLI tests
    main()
