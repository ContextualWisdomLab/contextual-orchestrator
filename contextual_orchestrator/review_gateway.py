"""Bootstrap a local authenticated gateway for trusted CI model reviews.

The declared provider keys arrive from a deployment environment only as bootstrap
transport. They are immediately registered in the process-local KV, after
which model discovery and every provider request use the normal credential
registry path. This keeps the review sidecar useful without pretending that a
short-lived runner has a durable production credential store.
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
    """Register only caller-declared non-empty CI credentials in the KV.

    ``environment`` is bootstrap input only. ``credential_names`` is the
    deployment-supplied array/list policy boundary; surrounding environment
    variables that are not named there are deliberately not detected. The
    returned names contain no secret values and are suitable for diagnostics
    or tests.
    """
    requested_names = _validated_credential_names(credential_names)
    registered: list[str] = []
    for name in requested_names:
        value = environment.get(name, "").strip()
        if value:
            register_credential(name, value)
            registered.append(name)
    auth_value = environment.get(REVIEW_AUTH_CREDENTIAL_NAME, "").strip()
    if auth_value:
        register_credential(REVIEW_AUTH_CREDENTIAL_NAME, auth_value)
        registered.append(REVIEW_AUTH_CREDENTIAL_NAME)
    return tuple(registered)


def build_review_orchestrator(
    environment: Mapping[str, str] | None = None,
    *,
    max_agents: int = DEFAULT_REVIEW_AGENT_LIMIT,
    credential_names: Sequence[str] | None = None,
) -> TaskOrchestrator:
    """Build an enabled, cost-ranked orchestrator from discovered providers.

    A missing requested provider key is allowed so the sidecar can use an
    available subset. Starting with no requested provider key or no discovered
    model fails closed rather than silently falling back to a mock or fabricated
    model. Credentials present outside ``credential_names`` never enter the KV.
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

    chat_discovered = [model for model in discovered if is_chat_serving_candidate(model)]
    if not chat_discovered:
        raise NotConfigured("review gateway discovered no general chat models")
    price_book = PriceBook(InMemoryConfigStore())
    refresh_price_book(chat_discovered, price_book)
    selected = select_bootstrap_discovered_agents(chat_discovered, price_book, max_agents)
    if not selected:
        raise NotConfigured("review gateway selected no provider models")

    agents = [
        replace(
            agent_from_discovered(model, priority=index),
            disabled=False,
            tags=("review",),
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
