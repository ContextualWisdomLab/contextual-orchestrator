"""SearXNG stays on loopback and enables the JSON API web_search() calls."""

from __future__ import annotations

from pathlib import Path

COMPOSE = Path(__file__).parents[1] / "compose.searxng.yaml"


def test_searxng_is_loopback_only_and_enables_json() -> None:
    text = COMPOSE.read_text(encoding="utf-8")
    assert "127.0.0.1:" in text
    assert "0.0.0.0:" not in text
    assert "cap_drop: [ALL]" in text
    assert "read_only: true" in text
    assert "sha256:3284e8900e9b3e5df284ae8c48a26851ae2eff6f99b4b0b18ec3da5a4d9095c3" in text
    assert "- json" in text
    assert "ultrasecretkey" not in text
    assert "SEARXNG_SECRET" in text
