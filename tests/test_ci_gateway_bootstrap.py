"""CI gateway bootstrap contracts."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from contextual_orchestrator.credentials import get_credential
from contextual_orchestrator.model_discovery import PROVIDER_MODEL_SOURCES


def _bootstrap_module():
    path = Path(__file__).parents[1] / "scripts" / "ci" / "serve_seeded_gateway.py"
    spec = importlib.util.spec_from_file_location("serve_seeded_gateway", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_seed_credentials_copies_present_provider_keys_into_kv(monkeypatch) -> None:
    module = _bootstrap_module()
    assert module.PROVIDER_KEY_ENV_NAMES == tuple(
        dict.fromkeys(source.credential_name for source in PROVIDER_MODEL_SOURCES)
    )
    for name in module.PROVIDER_KEY_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "router-secret")
    monkeypatch.setenv("OPENCODE_ZEN_API_KEY", "zen-secret")

    assert module.seed_credentials_from_bootstrap_env() == [
        "OPENROUTER_API_KEY",
        "OPENCODE_ZEN_API_KEY",
    ]
    assert "OPENROUTER_API_KEY" not in module.os.environ
    assert "OPENCODE_ZEN_API_KEY" not in module.os.environ
    monkeypatch.setenv("OPENCODE_ZEN_API_KEY", "changed-after-bootstrap")
    assert get_credential("OPENCODE_ZEN_API_KEY") == "zen-secret"
