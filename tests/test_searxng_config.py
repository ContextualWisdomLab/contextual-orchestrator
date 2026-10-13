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


def test_write_settings_refuses_shared_parent_without_changing_permissions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject a shared directory without changing it or publishing settings."""
    shared = tmp_path / "shared"
    shared.mkdir(mode=0o755)
    shared.chmod(0o755)
    target = shared / "settings.yml"
    target.write_text("retained settings\n", encoding="utf-8")
    rendered = []
    monkeypatch.setattr(searxng_config, "render_searxng_settings", lambda: rendered.append(True) or "new settings\n")

    try:
        with pytest.raises(ValueError, match="owner-private"):
            searxng_config.write_searxng_settings(target)
    finally:
        assert os.stat(shared).st_mode & 0o777 == 0o755
        assert target.read_text(encoding="utf-8") == "retained settings\n"
        assert rendered == []
        assert sorted(path.name for path in shared.iterdir()) == ["settings.yml"]


def test_write_settings_reuses_existing_private_parent_without_chmod(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pre-existing private directory remains usable without permission mutation."""
    parent = tmp_path / "private"
    parent.mkdir(mode=0o700)
    target = parent / "settings.yml"
    target.write_text("old settings\n", encoding="utf-8")
    monkeypatch.setattr(searxng_config, "render_searxng_settings", lambda: "new settings\n")
    def unexpected_chmod(*_args, **_kwargs):
        raise AssertionError("existing parent permissions must not be changed")
    monkeypatch.setattr(searxng_config.os, "chmod", unexpected_chmod)

    searxng_config.write_searxng_settings(target)

    assert target.read_text(encoding="utf-8") == "new settings\n"
    assert os.stat(parent).st_mode & 0o777 == 0o700
    assert os.stat(target).st_mode & 0o777 == 0o644
    assert sorted(path.name for path in parent.iterdir()) == ["settings.yml"]


def test_write_settings_is_atomic_with_protected_parent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Protect the host directory while keeping the file readable by UID 977."""
    monkeypatch.setattr(searxng_config, "render_searxng_settings", lambda: "settings\n")
    target = tmp_path / "secrets" / "settings.yml"

    searxng_config.write_searxng_settings(target)

    assert target.read_text(encoding="utf-8") == "settings\n"
    assert os.stat(target.parent).st_mode & 0o777 == 0o700
    assert os.stat(target).st_mode & 0o777 == 0o644
