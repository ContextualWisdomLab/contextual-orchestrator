"""Bootstrap a local authenticated gateway for trusted CI model reviews.

The declared provider keys arrive from a deployment environment only as bootstrap
transport. They are immediately registered in the process-local KV, after
which model discovery and every provider request use the normal credential
registry path. This keeps the review sidecar useful without pretending that a
short-lived runner has a durable production credential store.

Credential registration and ``orchestrator/free`` candidate admission are
separate contracts. A deployment may register every accepted provider,
including OpenAI and a CI-seeded ``OPENCODE_ZEN_API_KEY``, while the free
review pool admits only the provider-account sources explicitly authorized
for that pool and explicitly supplied for the current sidecar bootstrap.
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass, replace
from typing import Mapping, Sequence

from .credentials import NotConfigured, get_credential, register_credential
from .model_discovery import (
    DiscoveredModel,
    agent_from_discovered,
    discover_all_models,
    general_free_serving_candidates,
)
from .orchestrator import ModelClient, TaskOrchestrator
from .provider_bootstrap import PROVIDER_ACCEPTED_CREDENTIAL_NAMES
from .server import SecurityConfig, serve

REVIEW_CREDENTIAL_NAMES = PROVIDER_ACCEPTED_CREDENTIAL_NAMES
REVIEW_FREE_POOL_CREDENTIAL_NAMES = (
    "BYTEZ_API_KEY",
    "NVIDIA_NIM_API_KEY",
    "NVIDIA_NIM_API_KEY_SUB",
    "OPENROUTER_API_KEY",
    "OPENCODE_ZEN_API_KEY",
    "EXPERIENTAL_LABS_API_KEY",
)
"""Provider-account sources authorized to contribute to ``orchestrator/free``.

This is a pool-admission policy, not the bootstrap credential inventory.
Default bootstrap registers every accepted provider credential that is present,
including optional ``OPENCODE_ZEN_API_KEY``, so a CI-seeded OpenCode key is not
dropped before admission. ``OPENAI_API_KEY`` may be registered and globally
discovered, but a model whose credential source is OpenAI is never admitted to
this free review pool. ``OPENCODE_ZEN_API_KEY`` is the shared source for
OpenCode Zen and OpenCode Go; only rows that already satisfy the shared
general-free serving contract enter the pool.
"""

REVIEW_AUTH_CREDENTIAL_NAME = "CONTEXTUAL_ORCHESTRATOR_TOKEN"

REVIEW_READINESS_CONTRACT_VERSION = "1"
"""Versioned owner readiness/admission contract for the free review pool.

Consumers pin this version to know exactly which readiness/admission
predicates the owner applied. It is bumped whenever a predicate, its
evidence source, or the returned provenance shape changes, so a leaf
caller can delete its own duplicated routing preflight instead of guessing
which owner contract is live.
"""


@dataclass(frozen=True)
class ReviewModelAdmission:
    """Typed, request-scoped provenance for one admitted review-pool model.

    Every field is owner-produced evidence about *why* the candidate is
    admitted, so a consumer never has to re-derive eligibility, re-probe
    readiness, or apply its own provider/model/fallback heuristics.
    """

    contract_version: str
    model_id: str
    provider_name: str
    credential_key: str
    tags: tuple[str, ...]
    max_output_tokens: int | None
    context_window: int | None


def review_model_admission(
    model: DiscoveredModel,
    *,
    tags: Sequence[str] = (),
) -> ReviewModelAdmission:
    """Return typed provenance for one already-admitted review-pool model.

    Admission itself happened in :func:`build_review_orchestrator`; this only
    serializes the owner's evidence so a consumer can consume it directly
    instead of re-deriving eligibility, readiness, or ordering.
    """
    return ReviewModelAdmission(
        contract_version=REVIEW_READINESS_CONTRACT_VERSION,
        model_id=model.model_id,
        provider_name=model.provider_name,
        credential_key=model.credential_name,
        tags=tuple(tags),
        max_output_tokens=model.max_output_tokens,
        context_window=model.context_window,
    )


def review_pool_admissions(
    agents: Sequence[Any],
) -> list[ReviewModelAdmission]:
    """Project a built review pool into versioned, consumer-readable provenance.

    The owner exposes this so a caller can send only the gateway token and
    ``model: orchestrator/free`` -- no provider/model/fallback parameters,
    no credential eligibility, no candidate catalog, no probing.
    """
    return [
        ReviewModelAdmission(
            contract_version=REVIEW_READINESS_CONTRACT_VERSION,
            model_id=str(getattr(agent, "model", "")),
            provider_name=str(getattr(agent, "provider_name", "") or ""),
            credential_key=str(getattr(agent, "credential_key", "") or ""),
            tags=tuple(getattr(agent, "tags", ()) or ()),
            max_output_tokens=getattr(agent, "max_output_tokens", None),
            context_window=getattr(agent, "context_window", None),
        )
        for agent in agents
    ]


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
    """Apply source policy after the shared blind-free serving eligibility rule."""
    admitted_credentials = frozenset(REVIEW_FREE_POOL_CREDENTIAL_NAMES)
    return [
        model
        for model in general_free_serving_candidates(list(discovered))
        if model.credential_name in admitted_credentials
    ]


def build_review_orchestrator(
    environment: Mapping[str, str] | None = None,
    *,
    credential_names: Sequence[str] | None = None,
) -> TaskOrchestrator:
    """Build the free review orchestrator from current bootstrap credentials.

    A missing requested provider key is allowed so bootstrap can use an
    available subset. All requested credentials, including ``OPENAI_API_KEY``,
    may be registered and globally discovered. Candidate admission is a
    separate boundary: candidates must satisfy the shared general-free serving
    contract, be sourced from ``REVIEW_FREE_POOL_CREDENTIAL_NAMES``, and belong
    to a provider credential actually registered by this bootstrap call.
    Therefore a previously stored OpenAI credential cannot enter the free pool,
    and an unrelated previously stored free-provider credential cannot escape
    the caller-declared bootstrap scope.

    Every candidate satisfying those evidence-backed admission predicates is
    retained. This boundary does not impose a candidate-count cap, provider
    quota, price-derived ordering, hand-assigned priority, or fallback ranking.
    Any subsequent model choice remains the routing layer's responsibility and
    must be supported by its own executable evidence contract.
    """
    requested_names = _validated_credential_names(credential_names)
    source_environment = os.environ if environment is None else environment
    registered = register_review_credentials(
        source_environment, credential_names=requested_names
    )
    registered_provider_names = frozenset(registered) & frozenset(requested_names)
    if not registered_provider_names:
        raise NotConfigured("review gateway requires at least one provider credential")

    discovered, errors = discover_all_models()
    if not discovered:
        providers = ", ".join(sorted({error.provider_name for error in errors}))
        detail = f"; failed providers: {providers}" if providers else ""
        raise NotConfigured(f"review gateway discovered no provider models{detail}")

    free_discovered = [
        model
        for model in _free_review_candidates(discovered)
        if model.credential_name in registered_provider_names
    ]
    if not free_discovered:
        raise NotConfigured(
            "review gateway discovered no eligible zero-cost general chat models"
        )

    agents = []
    for model in free_discovered:
        discovered_agent = agent_from_discovered(model, priority=0)
        agents.append(
            replace(
                discovered_agent,
                disabled=False,
                tags=(*discovered_agent.tags, "review", "cost:free"),
                priority=0,
            )
        )
    return TaskOrchestrator(
        agents,
        client=ModelClient(),
    )


def _build_parser() -> argparse.ArgumentParser:
    """Create the sidecar CLI parser with loopback-safe defaults."""
    parser = argparse.ArgumentParser(description="Run the contextual review gateway sidecar.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18080)
    parser.add_argument(
        "--credential-name",
        dest="credential_names",
        action="append",
        choices=PROVIDER_ACCEPTED_CREDENTIAL_NAMES,
        help=(
            "Provider credential name to bootstrap; repeat to supply an ordered "
            "credential array. Defaults to every accepted provider credential."
        ),
    )
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
    try:
        register_review_credentials(
            os.environ,
            credential_names=args.credential_names,
        )
    except ValueError as exc:
        parser.error(str(exc))
    auth_token = args.auth_token or get_credential(args.auth_token_key)
    if not auth_token:
        raise SystemExit(f"KV credential {args.auth_token_key!r} or --auth-token is required")
    orchestrator = build_review_orchestrator(
        credential_names=args.credential_names,
    )
    serve(
        orchestrator,
        host=args.host,
        port=args.port,
        security=SecurityConfig(auth_token=auth_token),
    )


if __name__ == "__main__":  # pragma: no cover
    main()
