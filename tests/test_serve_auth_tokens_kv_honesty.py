"""Serve-time API tokens must come from CLI or KV, never process env.

``python -m contextual_orchestrator --serve`` still defaulted
``--auth-token`` / ``--admin-token`` / ``--inference-token`` from
``os.environ.get("CONTEXTUAL_ORCHESTRATOR_*")``. A buyer who seeded the
KV and then rotated or unset the process env would keep serving the
stale env value — or, worse, a process dump would expose the live
gateway token that the KV registry was supposed to own.

NIST Joint Task Force. (2020). *Security and privacy controls for
information systems and organizations* (NIST SP 800-53 Rev. 5)
(AC-3, SC-12). National Institute of Standards and Technology.
https://doi.org/10.6028/NIST.SP.800-53r5

Barker, E. (2020). *Recommendation for key management: Part 1 –
General* (NIST SP 800-57 Part 1 Rev. 5). National Institute of
Standards and Technology. https://doi.org/10.6028/NIST.SP.800-57pt1r5
"""

from __future__ import annotations

import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator.credentials import (  # noqa: E402
    InMemoryCredentialBackend,
    register_credential,
    resolve_serve_auth_tokens,
    set_backend,
)


def _fresh_kv() -> None:
    set_backend(InMemoryCredentialBackend())


def test_env_token_is_ignored_when_kv_and_cli_are_empty() -> None:
    """Process env is bootstrap transport, not the runtime source."""
    _fresh_kv()
    os.environ["CONTEXTUAL_ORCHESTRATOR_TOKEN"] = "env-token-must-not-be-used"
    os.environ["CONTEXTUAL_ORCHESTRATOR_ADMIN_TOKEN"] = "env-admin-must-not-be-used"
    os.environ["CONTEXTUAL_ORCHESTRATOR_INFERENCE_TOKEN"] = "env-inference-must-not-be-used"
    try:
        auth_token, admin_token, inference_token = resolve_serve_auth_tokens()
        assert auth_token == ""
        assert admin_token == ""
        assert inference_token == ""
    finally:
        os.environ.pop("CONTEXTUAL_ORCHESTRATOR_TOKEN", None)
        os.environ.pop("CONTEXTUAL_ORCHESTRATOR_ADMIN_TOKEN", None)
        os.environ.pop("CONTEXTUAL_ORCHESTRATOR_INFERENCE_TOKEN", None)
        set_backend(None)


def test_kv_gateway_auth_token_wins_over_env() -> None:
    """Buyer seeded the KV; a leftover env value must not override it."""
    _fresh_kv()
    register_credential("gateway_auth_token", "kv-gateway-token")
    os.environ["CONTEXTUAL_ORCHESTRATOR_TOKEN"] = "env-stale-token"
    try:
        auth_token, admin_token, inference_token = resolve_serve_auth_tokens()
        assert auth_token == "kv-gateway-token"
        assert admin_token == ""
        assert inference_token == ""
    finally:
        os.environ.pop("CONTEXTUAL_ORCHESTRATOR_TOKEN", None)
        set_backend(None)


def test_historical_env_name_alias_resolves_from_kv() -> None:
    """register-credential --name CONTEXTUAL_ORCHESTRATOR_TOKEN still works."""
    _fresh_kv()
    register_credential("CONTEXTUAL_ORCHESTRATOR_TOKEN", "alias-kv-token")
    auth_token, _, _ = resolve_serve_auth_tokens()
    assert auth_token == "alias-kv-token"
    set_backend(None)


def test_cli_auth_token_wins_over_kv() -> None:
    """Explicit --auth-token is operator input, not env, and wins."""
    _fresh_kv()
    register_credential("gateway_auth_token", "kv-gateway-token")
    auth_token, _, _ = resolve_serve_auth_tokens(auth_token="cli-operator-token")
    assert auth_token == "cli-operator-token"
    set_backend(None)


def test_split_admin_and_inference_tokens_resolve_from_kv() -> None:
    """Split-plane serve tokens are first-class KV secrets."""
    _fresh_kv()
    register_credential("gateway_admin_token", "kv-admin-token")
    register_credential("gateway_inference_token", "kv-inference-token")
    auth_token, admin_token, inference_token = resolve_serve_auth_tokens()
    assert auth_token == ""
    assert admin_token == "kv-admin-token"
    assert inference_token == "kv-inference-token"
    set_backend(None)


def test_whitespace_cli_token_is_omit_and_falls_back_to_kv() -> None:
    _fresh_kv()
    register_credential("gateway_auth_token", "kv-gateway-token")
    auth_token, _, _ = resolve_serve_auth_tokens(auth_token="   ")
    assert auth_token == "kv-gateway-token"
    set_backend(None)


if __name__ == "__main__":
    test_env_token_is_ignored_when_kv_and_cli_are_empty()
    test_kv_gateway_auth_token_wins_over_env()
    test_historical_env_name_alias_resolves_from_kv()
    test_cli_auth_token_wins_over_kv()
    test_split_admin_and_inference_tokens_resolve_from_kv()
    test_whitespace_cli_token_is_omit_and_falls_back_to_kv()
    print("ok")
