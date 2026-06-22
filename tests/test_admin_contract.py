from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.admin import ADMIN_HTML  # noqa: E402


def test_admin_surface_exists_for_enterprise_operations() -> None:
    assert "Agent Pool" in ADMIN_HTML
    assert "Orchestration Policy" in ADMIN_HTML
    assert "Audit &amp; Compliance" in ADMIN_HTML
    assert "/admin/simulate" in ADMIN_HTML
    assert "ADMIN_TRANSLATIONS" not in ADMIN_HTML
    assert "source_basis_text" in ADMIN_HTML


def test_admin_state_exposes_agents_without_secrets() -> None:
    state = TaskOrchestrator(
        [ModelAgent("worker_agent", "gpt-example", "https://example.test/v1", "SECRET_ENV", tags=("coding",))]
    ).admin_state()

    assert state["agents"][0]["id"] == "worker_agent"
    assert "SECRET_ENV" not in str(state)
    assert state["policy"]["workflow_steps"] == ["thinker", "worker", "verifier", "synthesizer"]
    assert state["policy"]["supported_locales"] == ["en", "ko"]


if __name__ == "__main__":
    test_admin_surface_exists_for_enterprise_operations()
    test_admin_state_exposes_agents_without_secrets()
    print("ok")
