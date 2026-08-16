"""Noema is a first-class /v1 consumer (review + other jobs), not an OpenCode sidecar."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_noema_is_named_as_v1_consumer_in_agent_docs() -> None:
    agents = _read("AGENTS.md")
    claude = _read("CLAUDE.md")
    architecture = _read("docs/architecture.md")
    rest = _read("docs/rest_api_design.md")
    for text in (agents, claude, architecture, rest):
        assert "Noema" in text
        assert "/v1" in text


def test_noema_is_not_documented_as_opencode_only() -> None:
    agents = _read("AGENTS.md")
    assert "multi-purpose" in agents.lower() or "review + other" in agents.lower() or "review and other" in agents.lower()
    assert "OpenCode review pipeline is separate" in agents or "OpenCode review pipeline" in agents


if __name__ == "__main__":
    test_noema_is_named_as_v1_consumer_in_agent_docs()
    test_noema_is_not_documented_as_opencode_only()
    print("ok")
