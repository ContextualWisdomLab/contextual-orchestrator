"""Bootstrap a local authenticated gateway for trusted CI model reviews.

The declared provider keys arrive from a deployment environment only as bootstrap
transport. They are immediately registered in the process-local KV, after
which model discovery and every provider request use the normal credential
registry path. This keeps the review sidecar useful without pretending that a
short-lived runner has a durable production credential store.

Credential registration and ``orchestrator/free`` candidate admission are
separate contracts. A deployment may register every configured provider,
including OpenAI, while the free review pool admits only the provider-account
sources explicitly authorized for that pool.
"""

from __future__ import annotations

import argparse
import os
from dataclasses import replace
from typing import Mapping, Sequence

from .credentials import NotConfigured, get_credential, register_credential
from .cost_ledger import PriceBook
from .kv_config import InMemoryConfigStore
from .model_discovery import (
    DiscoveredModel,
    agent_from_discovered,
    discover_all_models,
    refresh_price_book,
    select_bootstrap_discovered_agents,
)
from .orchestrator import ModelClient, TaskOrchestrator
from .provider_bootstrap import (
    PROVIDER_ACCEPTED_CREDENTIAL_NAMES,
    PROVIDER_CREDENTIAL_NAMES,
    is_chat_serving_candidate,
)
from .server import SecurityConfig, serve

REVIEW_CREDENTIAL_NAMES = PROVIDER_CREDENTIAL_NAMES
REVIEW_FREE_POOL_CREDENTIAL_NAMES = (
    "BYTEZ_API_KEY",
    "NVIDIA_NIM_API_KEY",
    "NVIDIA_NIM_API_KEY_SUB",
    "OPENROUTER_API_KEY",
)
"""Provider-account sources authorized to contribute to ``orchestrator/free``.

This is a pool-admission policy, not the bootstrap credential inventory.
``OPENAI_API_KEY`` may be registered and globally discovered, but a model whose
credential source is OpenAI is never admitted to this free review pool.
"""

DEFAULT_REVIEW_AGENT_LIMIT = 12
REVIEW_AUTH_CREDENTIAL_NAME = "CONTEXTUAL_ORCHESTRATOR_TOKEN"


def _validated_credential_names(
    credential_names: Sequence[str] | None,
) -> tuple[str, ...]:
    """Return one ordered, duplicate-free provider credential specification."""
    names = tuple(REVIEW_CREDENTIAL_NAMES if credential_names is None else credential_names)
    if len(names) != len(set(names)):
        raise ValueError("duplicate credential names are not allowed")
    unknown = sorted(set(names) - set(PROVIDER_ACCEPTED_CREDENTIAL_NAMES))
    if unknown:
        raise ValueError("unknown credential names are not allowed")
    return names


def register_review_credentials(
    environment: Mapping[str, str],
    *,
    credential_names: Sequence[str] | None = None,
) -> tuple[str, ...]:
    """Register caller-declared non-empty CI credentials in the process KV.

    ``environment`` is bootstrap input only. ``credential_names`` is an ordered
    caller-supplied credential specification; it controls what bootstrap copies
    into this process, not what ``orchestrator/free`` is allowed to serve.
    Mounted CR/LF line endings are removed while every other credential byte is
    preserved, matching the provider bootstrap normalization contract.
    """
    requested_names = _validated_credential_names(credential_names)
    registered: list[str] = []
    for name in requested_names:
        raw_value = environment.get(name, "")
        value = raw_value.rstrip("\r\n") if isinstance(raw_value, str) else ""
        if value and value.strip():
            register_credential(name, value)
            registered.append(name)
    raw_auth_value = environment.get(REVIEW_AUTH_CREDENTIAL_NAME, "")
    auth_value = (
        raw_auth_value.rstrip("\r\n") if isinstance(raw_auth_value, str) else ""
    )
    if auth_value and auth_value.strip():
        register_credential(REVIEW_AUTH_CREDENTIAL_NAME, auth_value)
        registered.append(REVIEW_AUTH_CREDENTIAL_NAME)
    return tuple(registered)


def _free_review_candidates(
    discovered: Sequence[DiscoveredModel],
) -> list[DiscoveredModel]:
    """Apply the explicit provider-source and zero-cost free-pool contract."""
    admitted_credentials = frozenset(REVIEW_FREE_POOL_CREDENTIAL_NAMES)
    return [
        model
        for model in discovered
        if model.credential_name in admitted_credentials
        and model.is_free
        and is_chat_serving_candidate(model)
    ]


def build_review_orchestrator(
    environment: Mapping[str, str] | None = None,
    *,
    max_agents: int = DEFAULT_REVIEW_AGENT_LIMIT,
    credential_names: Sequence[str] | None = None,
) -> TaskOrchestrator:
    """Build the free review orchestrator from globally discovered providers.

    A missing requested provider key is allowed so bootstrap can use an
    available subset. All requested credentials, including ``OPENAI_API_KEY``,
    may be registered and globally discovered. Candidate admission is a
    separate source-boundary check: only models sourced from
    ``REVIEW_FREE_POOL_CREDENTIAL_NAMES`` with explicit zero-cost evidence may
    enter the review pool. Therefore a previously stored OpenAI credential also
    cannot bypass the free-pool boundary.
    """
    if type(max_agents) is not int or max_agents < 1:
        raise ValueError("max_agents must be a positive integer")
    requested_names = _validated_credential_names(credential_names)
    source_environment = os.environ if environment is None else environment
    registered = register_review_credentials(
        source_environment, credential_names=requested_names
    )
    if not any(name in registered for name in requested_names):
        raise NotConfigured("review gateway requires at least one provider credential")

    discovered, errors = discover_all_models()
    if not discovered:
        providers = ", ".join(sorted({error.provider_name for error in errors}))
        detail = f"; failed providers: {providers}" if providers else ""
        raise NotConfigured(f"review gateway discovered no provider models{detail}")

    free_discovered = _free_review_candidates(discovered)
    if not free_discovered:
        raise NotConfigured(
            "review gateway discovered no eligible zero-cost general chat models"
        )
    price_book = PriceBook(InMemoryConfigStore())
    refresh_price_book(free_discovered, price_book)
    selected = select_bootstrap_discovered_agents(
        free_discovered, price_book, max_agents
    )
    if not selected:
        raise NotConfigured("review gateway selected no provider models")

    agents = [
        replace(
            agent_from_discovered(model, priority=index),
            disabled=False,
            tags=("review", "cost:free"),
            priority=-index,
        )
        for index, model in enumerate(selected)
    ]
    return TaskOrchestrator(
        agents,
        client=ModelClient(max_output_tokens=32768),
    )


def _build_parser() -> argparse.ArgumentParser:
    """Create the sidecar CLI parser with loopback-safe defaults."""
    parser = argparse.ArgumentParser(description="Run the contextual review gateway sidecar.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18080)
    parser.add_argument("--max-agents", type=int, default=DEFAULT_REVIEW_AGENT_LIMIT)
    parser.add_argument(
        "--auth-token",
        default="",
        help="Explicit local bearer token; otherwise resolve --auth-token-key from the KV.",
    )
    parser.add_argument("--auth-token-key", default=REVIEW_AUTH_CREDENTIAL_NAME)
    return parser


def main() -> None:
    """Discover providers and serve the authenticated OpenAI-compatible sidecar."""
    parser = _build_parser()
    args = parser.parse_args()
    if args.max_agents < 1:
        parser.error("--max-agents must be a positive integer")
    register_review_credentials(os.environ)
    auth_token = args.auth_token or get_credential(args.auth_token_key)
    if not auth_token:
        raise SystemExit(f"KV credential {args.auth_token_key!r} or --auth-token is required")
    orchestrator = build_review_orchestrator(max_agents=args.max_agents)
    serve(
        orchestrator,
        host=args.host,
        port=args.port,
        security=SecurityConfig(auth_token=auth_token),
    )


if __name__ == "__main__":  # pragma: no cover
    main()
