"""Bootstrap a local authenticated gateway for trusted CI model reviews.

The five provider keys arrive from a deployment environment only as bootstrap
transport. They are immediately registered in the process-local KV, after
which model discovery and every provider request use the normal credential
registry path. This keeps the review sidecar useful without pretending that a
short-lived runner has a durable production credential store.
"""

from __future__ import annotations

import argparse
import os
from dataclasses import replace
from typing import Mapping

from .credentials import NotConfigured, register_credential
from .cost_ledger import PriceBook
from .kv_config import InMemoryConfigStore
from .model_discovery import (
    agent_from_discovered,
    discover_all_models,
    refresh_price_book,
    select_top_n_cheapest_discovered_agents,
)
from .orchestrator import ModelClient, TaskOrchestrator
from .server import SecurityConfig, serve

REVIEW_CREDENTIAL_NAMES: tuple[str, ...] = (
    "BYTEZ_API_KEY",
    "NVIDIA_NIM_API_KEY",
    "NVIDIA_NIM_API_KEY_SUB",
    "OPENROUTER_API_KEY",
    "OPENAI_API_KEY",
)
DEFAULT_REVIEW_AGENT_LIMIT = 12


def register_review_credentials(environment: Mapping[str, str]) -> tuple[str, ...]:
    """Register non-empty CI provider keys in the process-local KV.

    ``environment`` is bootstrap input only. The returned names contain no
    secret values and are suitable for diagnostics or tests.
    """
    registered: list[str] = []
    for name in REVIEW_CREDENTIAL_NAMES:
        value = environment.get(name, "").strip()
        if value:
            register_credential(name, value)
            registered.append(name)
    return tuple(registered)


def build_review_orchestrator(
    environment: Mapping[str, str] | None = None,
    *,
    max_agents: int = DEFAULT_REVIEW_AGENT_LIMIT,
) -> TaskOrchestrator:
    """Build an enabled, cost-ranked orchestrator from discovered providers.

    A missing provider key is allowed so the sidecar can use an available
    subset. Starting with no provider key or no discovered model fails closed
    rather than silently falling back to a mock or fabricated model.
    """
    if type(max_agents) is not int or max_agents < 1:
        raise ValueError("max_agents must be a positive integer")
    source_environment = os.environ if environment is None else environment
    registered = register_review_credentials(source_environment)
    if not registered:
        raise NotConfigured("review gateway requires at least one provider credential")

    discovered, errors = discover_all_models()
    if not discovered:
        providers = ", ".join(sorted({error.provider_name for error in errors}))
        detail = f"; failed providers: {providers}" if providers else ""
        raise NotConfigured(f"review gateway discovered no provider models{detail}")

    price_book = PriceBook(InMemoryConfigStore())
    refresh_price_book(discovered, price_book)
    selected = select_top_n_cheapest_discovered_agents(discovered, price_book, max_agents)
    if not selected:
        raise NotConfigured("review gateway selected no provider models")

    agents = [
        replace(
            agent_from_discovered(model, priority=index),
            disabled=False,
            # The discovery catalog does not advertise reasoning, coding, or
            # verification support. ``review`` is the gateway purpose, not a
            # fabricated provider capability.
            tags=("review",),
            # TaskOrchestrator ranks larger priorities first. Discovery is
            # already cheapest-first, so preserve that order for routing.
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
        default=os.environ.get("CONTEXTUAL_ORCHESTRATOR_TOKEN", ""),
        help="Bearer token for the local review gateway (prefer the environment bootstrap).",
    )
    return parser


def main() -> None:
    """Discover providers and serve the authenticated OpenAI-compatible sidecar."""
    args = _build_parser().parse_args()
    if not args.auth_token:
        raise SystemExit("CONTEXTUAL_ORCHESTRATOR_TOKEN or --auth-token is required")
    orchestrator = build_review_orchestrator(max_agents=args.max_agents)
    serve(
        orchestrator,
        host=args.host,
        port=args.port,
        security=SecurityConfig(auth_token=args.auth_token),
    )


if __name__ == "__main__":  # pragma: no cover
    main()
