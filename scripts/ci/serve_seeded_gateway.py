#!/usr/bin/env python3
"""Bootstrap-transport gateway launcher for CI agent loops.

Seeds the five provider keys from GitHub-secrets-provided environment
variables into the process-local KV credential registry (env is used ONLY as
bootstrap transport into the KV, never read again at request time), then runs
the normal ``--serve`` entrypoint in this same process so discovery and
routing resolve keys through ``get_credential()`` exactly like production.

Usage:
    python scripts/ci/serve_seeded_gateway.py [extra server args...]

Provider key environment variables (all optional; missing ones are skipped):
    OPENAI_API_KEY, OPENROUTER_API_KEY, OPENCODE_ZEN_API_KEY, BYTEZ_API_KEY,
    NVIDIA_NIM_API_KEY, NVIDIA_NIM_API_KEY_SUB
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from contextual_orchestrator.credentials import (  # noqa: E402
    InMemoryCredentialBackend,
    register_credential,
    set_backend,
)

PROVIDER_KEY_ENV_NAMES = (
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "OPENCODE_ZEN_API_KEY",
    "BYTEZ_API_KEY",
    "NVIDIA_NIM_API_KEY",
    "NVIDIA_NIM_API_KEY_SUB",
)


def seed_credentials_from_bootstrap_env() -> list[str]:
    """Register every present provider key into the KV; return registered names."""
    set_backend(InMemoryCredentialBackend())
    seeded: list[str] = []
    for credential_name in PROVIDER_KEY_ENV_NAMES:
        value = os.environ.get(credential_name)
        # Bootstrap transport only: the CI job injects secrets.<NAME> into this
        # process environment; nothing reads os.environ again after this.
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
