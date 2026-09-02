"""Bootstrap-transport gateway launcher for CI agent loops.

Seeds the provider keys from GitHub-secrets-provided environment variables
into the process-local KV credential registry (env is used ONLY as bootstrap
transport into the KV, never read again at request time), then runs the
normal ``--serve`` entrypoint in this same process so discovery and routing
resolve keys through ``get_credential()`` exactly like production.

Usage:
    python scripts/ci/serve_seeded_gateway.py [extra server args...]

Bootstrap environment variables (all optional; missing ones are skipped --
this list is derived from ``PROVIDER_MODEL_SOURCES`` and grows automatically
as new providers are added there):
    OPENAI_API_KEY, OPENROUTER_API_KEY, OPENCODE_ZEN_API_KEY,
    OPENCODE_GO_API_KEY, BYTEZ_API_KEY, NVIDIA_NIM_API_KEY,
    NVIDIA_NIM_API_KEY_SUB, CONTEXTUAL_ORCHESTRATOR_TOKEN
"""

from __future__ import annotations

import os

from contextual_orchestrator.credentials import (
    InMemoryCredentialBackend,
    register_credential,
    set_backend,
)
from contextual_orchestrator.model_discovery import PROVIDER_MODEL_SOURCES

PROVIDER_KEY_ENV_NAMES = tuple(
    dict.fromkeys(source.credential_name for source in PROVIDER_MODEL_SOURCES)
)
SERVER_AUTH_ENV_NAME = "CONTEXTUAL_ORCHESTRATOR_TOKEN"


def seed_credentials_from_bootstrap_env() -> list[str]:
    """Register every present CI bootstrap credential; return registered names."""
    set_backend(InMemoryCredentialBackend())
    seeded: list[str] = []
    for credential_name in (*PROVIDER_KEY_ENV_NAMES, SERVER_AUTH_ENV_NAME):
        value = os.environ.pop(credential_name, None)
        # Bootstrap transport only: the trusted CI job injects each value into
        # this process environment; nothing reads os.environ again after this.
        if value:
            register_credential(credential_name, value)
            seeded.append(credential_name)
    return seeded


def main() -> None:
    """Seed the KV then hand control to the standard CLI serve path."""
    seeded = seed_credentials_from_bootstrap_env()
    print(f"seeded_kv_credential_names={sorted(seeded)}", flush=True)
    if not seeded:
        print(
            "no provider credentials were provided; the gateway will serve its "
            "static agent pool only (auto-discovery will find nothing)",
            flush=True,
        )
    from contextual_orchestrator.__main__ import main as cli_main

    cli_main()


if __name__ == "__main__":
    main()
