"""SearXNG deployment settings come from the KV, never runtime secret env."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from contextual_orchestrator import searxng_config
from contextual_orchestrator.credentials import NotConfigured


def test_rendered_settings_use_exact_kv_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Render YAML from the two named KV entries with safe scalar encoding."""
    credentials = {
        "SEARXNG_SECRET": 'search "secret"',
        "WARDNET_EGRESS_PROXY_TOKEN": "proxy:/ token",
    }
    requested: list[str] = []

    def resolve(name: str) -> str | None:
        requested.append(name)
        return credentials.get(name)

    monkeypatch.setattr(searxng_config, "get_credential", resolve)
    rendered = searxng_config.render_searxng_settings()

    assert requested == ["SEARXNG_SECRET", "WARDNET_EGRESS_PROXY_TOKEN"]
    assert 'secret_key: "search \\"secret\\""' in rendered
    assert "http://wardnet:proxy%3A%2F%20token@172.30.0.2:8080" in rendered
    assert "formats:\n    - html\n    - json" in rendered


def test_missing_kv_credential_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """An absent deployment secret must not produce a partial settings file."""
    monkeypatch.setattr(searxng_config, "get_credential", lambda _: None)
    with pytest.raises(NotConfigured, match="SEARXNG_SECRET"):
        searxng_config.render_searxng_settings()


def test_write_settings_is_atomic_with_protected_parent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Protect the host directory while keeping the file readable by UID 977."""
    monkeypatch.setattr(searxng_config, "render_searxng_settings", lambda: "settings\n")
    target = tmp_path / "secrets" / "settings.yml"

    searxng_config.write_searxng_settings(target)

    assert target.read_text(encoding="utf-8") == "settings\n"
    assert os.stat(target.parent).st_mode & 0o777 == 0o700
    assert os.stat(target).st_mode & 0o777 == 0o644
