from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.admin import ADMIN_HTML, ADMIN_TRANSLATIONS  # noqa: E402


def test_admin_surface_exists_for_enterprise_operations() -> None:
    assert "Agent Pool" in ADMIN_HTML
    assert "Orchestration Policy" in ADMIN_HTML
    assert "Audit &amp; Compliance" in ADMIN_HTML
    assert "/admin/simulate" in ADMIN_HTML
    assert "ADMIN_TRANSLATIONS" not in ADMIN_HTML
    assert "source_basis_text" in ADMIN_HTML
    assert "include_orchestration_trace: true" in ADMIN_HTML
    assert 'data-view="evaluations"' in ADMIN_HTML
    assert 'data-view="datasets"' in ADMIN_HTML
    assert 'data-view="access"' in ADMIN_HTML
    assert "Access List Inspector" in ADMIN_HTML
    assert "Evaluation Replay" in ADMIN_HTML
    assert 'id="mobileView"' in ADMIN_HTML
    assert ADMIN_TRANSLATIONS["en"]["view_label"] == "View"
    assert 'for="mobileView" data-i18n="view_label"' in ADMIN_HTML
    assert "els.mobileView.addEventListener" in ADMIN_HTML
    assert 'data-section="agent-pool"' in ADMIN_HTML
    assert 'data-section="orchestration-policy"' in ADMIN_HTML
    assert 'id="agent-pool" tabindex="-1"' in ADMIN_HTML
    assert 'id="orchestration-policy" tabindex="-1"' in ADMIN_HTML
    assert "scrollIntoView" in ADMIN_HTML
    assert "preventScroll: true" in ADMIN_HTML
    assert "prefers-reduced-motion: reduce" in ADMIN_HTML
    assert 'behavior: reducedMotion ? "auto" : "smooth"' in ADMIN_HTML
    assert 'id="statusFilter"' in ADMIN_HTML
    assert 'option value="healthy" data-i18n="status_healthy"' in ADMIN_HTML
    assert 'option value="degraded" data-i18n="status_degraded"' in ADMIN_HTML
    assert "statusFilter: document.querySelector" in ADMIN_HTML
    assert 'els.statusFilter.addEventListener("change", renderAgents)' in ADMIN_HTML
    assert "function agentStatus(index)" in ADMIN_HTML
    assert "no_agents_match" in ADMIN_HTML
    assert ADMIN_TRANSLATIONS["en"]["no_agents_match"] == "No agents match the current filters."
    assert 'id="viewAudit" data-i18n="view_all"' in ADMIN_HTML
    assert "viewAudit: document.querySelector" in ADMIN_HTML
    assert 'els.viewAudit.addEventListener("click", () => showView("audit"))' in ADMIN_HTML
    assert 'id="agentSettings" aria-label="Agent settings"' in ADMIN_HTML
    assert "agentSettings: document.querySelector" in ADMIN_HTML
    assert 'els.agentSettings.addEventListener("click", () => showView("settings"))' in ADMIN_HTML
    assert 'id="registerAgent"' in ADMIN_HTML
    assert "registerAgent: document.querySelector" in ADMIN_HTML
    assert 'els.registerAgent.addEventListener("click", () => showView("integrations"))' in ADMIN_HTML
    assert ADMIN_TRANSLATIONS["en"]["no_agents_configured"] == "No agents are configured yet."
    assert '|| `<tr><td colspan="3" class="empty" data-i18n="no_agents_configured">${t("no_agents_configured")}</td></tr>`' in ADMIN_HTML


def test_admin_state_exposes_agents_without_secrets() -> None:
    state = TaskOrchestrator(
        [ModelAgent("worker_agent", "gpt-example", "https://example.test/v1", "SECRET_ENV", tags=("coding",))]
    ).admin_state()

    assert state["agents"][0]["id"] == "worker_agent"
    assert "SECRET_ENV" not in str(state)
    assert state["policy"]["workflow_steps"] == ["thinker", "worker", "verifier", "synthesizer"]
    assert state["policy"]["supported_locales"] == ["en", "ko"]


if __name__ == "__main__":  # pragma: no cover
    test_admin_surface_exists_for_enterprise_operations()
    test_admin_state_exposes_agents_without_secrets()
    print("ok")
