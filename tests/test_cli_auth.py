"""CLI server-auth resolution stays explicit or KV-backed."""

from __future__ import annotations

from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator.__main__ import _resolve_auth_token, main  # noqa: E402
from contextual_orchestrator.credentials import InMemoryCredentialBackend, set_backend  # noqa: E402


def test_auth_token_resolution_prefers_explicit_then_kv() -> None:
    backend = InMemoryCredentialBackend()
    backend.set("gateway_token", "from-kv")
    set_backend(backend)
    try:
        assert _resolve_auth_token("explicit", "gateway_token") == "explicit"
        assert _resolve_auth_token("", "gateway_token") == "from-kv"
        try:
            _resolve_auth_token("", "missing_token")
        except ValueError as exc:
            assert "not configured" in str(exc)
        else:  # pragma: no cover
            raise AssertionError("missing auth credential was accepted")
    finally:
        set_backend(None)


def test_partial_split_tokens_fail_before_kv_lookup() -> None:
    with patch.object(sys, "argv", ["contextual-orchestrator", "--serve", "--admin-token", "admin"]):
        with patch("contextual_orchestrator.__main__.get_credential", side_effect=AssertionError("KV lookup was premature")):
            try:
                main()
            except SystemExit as exc:
                assert exc.code == 2
            else:  # pragma: no cover
                raise AssertionError("partial split token mode must be rejected")


if __name__ == "__main__":
    test_auth_token_resolution_prefers_explicit_then_kv()
    test_partial_split_tokens_fail_before_kv_lookup()
    print("ok")
