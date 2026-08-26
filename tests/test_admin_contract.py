from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.admin import ADMIN_HTML, ADMIN_TRANSLATIONS  # noqa: E402


def test_admin_surface_exists_for_enterprise_operations() -> None:
    assert "Models" in ADMIN_HTML
    assert "Routing Policy" in ADMIN_HTML
    assert "Audit &amp; Compliance" in ADMIN_HTML
    assert '<tr><td>PII-001</td><td>Purpose-authorized roles</td><td>Field encryption and audited release</td></tr>' in ADMIN_HTML
    assert "PII-001" in ADMIN_HTML
    assert "Mask email, phone" not in ADMIN_HTML
    assert "/admin/simulate" in ADMIN_HTML
    assert "ADMIN_TRANSLATIONS" not in ADMIN_HTML
    assert "source_basis_text" in ADMIN_HTML
    assert "include_orchestration_trace: true" in ADMIN_HTML
    assert 'data-view="evaluations"' in ADMIN_HTML
    assert 'data-view="datasets"' in ADMIN_HTML
    assert 'data-view="access"' in ADMIN_HTML
    assert "Permission review" in ADMIN_HTML
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
    assert ADMIN_TRANSLATIONS["en"]["no_agents_match"] == (
        "No models match these filters. Clear a filter to see more models."
    )
    assert '{ pass: "ok", warn: "warning", fail: "failure" }[row.status]' in ADMIN_HTML
    assert ADMIN_TRANSLATIONS["en"]["readiness_ok"] == "Pass"
    assert ADMIN_TRANSLATIONS["ko"]["readiness_failure"] == "실패"
    assert 'id="viewAudit" data-i18n="view_all"' in ADMIN_HTML
    assert "viewAudit: document.querySelector" in ADMIN_HTML
    assert 'els.viewAudit.addEventListener("click", () => showView("audit"))' in ADMIN_HTML
    assert 'id="agentSettings" aria-label="Model settings"' in ADMIN_HTML
    assert "agentSettings: document.querySelector" in ADMIN_HTML
    assert 'els.agentSettings.addEventListener("click", () => showView("settings"))' in ADMIN_HTML
    assert 'id="registerAgent"' in ADMIN_HTML
    assert "registerAgent: document.querySelector" in ADMIN_HTML
    assert 'els.registerAgent.addEventListener("click", () => showView("integrations"))' in ADMIN_HTML
    assert 'id="modelGroupForm"' in ADMIN_HTML
    assert 'id="modelGroupName" required pattern=' in ADMIN_HTML
    assert 'id="modelGroupMembers" multiple required' in ADMIN_HTML
    assert 'role="status" aria-live="polite"' in ADMIN_HTML
    assert 'fetch("/api/v1/model_groups")' in ADMIN_HTML
    assert "(state.modelGroups || []).map" in ADMIN_HTML
    assert "hintCount" not in ADMIN_HTML
    assert "complex_hints" not in ADMIN_HTML
    assert 'method: exists ? "PATCH" : "POST"' in ADMIN_HTML
    assert 'method: "DELETE"' in ADMIN_HTML
    for key in (
        "model_groups_title",
        "group_name_label",
        "group_members_label",
        "save_group",
        "delete_group",
        "no_model_groups",
        "group_saved",
        "group_deleted",
    ):
        assert key in ADMIN_TRANSLATIONS["en"] and key in ADMIN_TRANSLATIONS["ko"]
    assert ADMIN_TRANSLATIONS["en"]["no_agents_configured"] == (
        "Add a model connection to start routing requests."
    )
    assert '|| `<tr><td colspan="3" class="empty" data-i18n="no_agents_configured">${t("no_agents_configured")}</td></tr>`' in ADMIN_HTML
    assert ADMIN_TRANSLATIONS["en"]["no_audit_events"] == "Run a workflow to create your first audit event."
    assert '|| `<tr><td colspan="3" class="empty" data-i18n="no_audit_events">${t("no_audit_events")}</td></tr>`' in ADMIN_HTML
    assert 'id="sessionForm"' in ADMIN_HTML
    assert 'id="sessionToken"' in ADMIN_HTML
    assert 'credentials: "same-origin"' in ADMIN_HTML
    assert '"/admin/session"' in ADMIN_HTML
    assert 'finally {\n        els.sessionToken.value = "";' in ADMIN_HTML
    assert 'headers: {"origin": window.location.origin}' not in ADMIN_HTML
    assert ADMIN_TRANSLATIONS["en"]["session_title"] == "Operator session"
    explanatory_keys = (
        "doc_viewer_desc",
        "doc_viewer_hint",
        "session_hint",
        "source_basis_text",
        "worker_latency",
        "planner_capacity",
    )
    internal_terms = (
        "clearfolio",
        "httponly",
        "bearer",
        "contextual_orchestrator_",
        "--clearfolio",
        "worker",
        "planner pool",
        "verifier",
        "synthesizer",
    )
    for locale in ("en", "ko"):
        copy = " ".join(ADMIN_TRANSLATIONS[locale][key] for key in explanatory_keys).lower()
        assert not any(term in copy for term in internal_terms)
    customer_html = ADMIN_HTML.lower()
    assert not any(
        term in customer_html
        for term in (
            "clearfolio integrated",
            "httponly</span>",
            "worker exceeded",
            "planner pool",
            ">worker<",
            ">verifier<",
            ">synthesizer<",
        )
    )
    assert "Mask email, phone" not in ADMIN_HTML
    assert "Field encryption and audited release" in ADMIN_HTML


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
