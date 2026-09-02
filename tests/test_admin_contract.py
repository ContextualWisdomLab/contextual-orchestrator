from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.admin import ADMIN_HTML, ADMIN_TRANSLATIONS  # noqa: E402


def test_admin_surface_exists_for_enterprise_operations() -> None:
    assert "Models" in ADMIN_HTML
    assert "Routing Policy" in ADMIN_HTML
    assert "Audit &amp; Compliance" in ADMIN_HTML
    assert "PII-001" not in ADMIN_HTML
    assert "No policy evidence is loaded. Open Audit to review recorded events." in ADMIN_HTML
    assert "No current alerts. Open Audit to review recent changes." in ADMIN_HTML
    assert "Analyze the architecture, implement the code" not in ADMIN_HTML
    assert "prod-us-east-1" not in ADMIN_HTML
    assert ">US East<" not in ADMIN_HTML
    assert 'data-i18n-placeholder="prompt_placeholder"' in ADMIN_HTML
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
    assert 'option value="active" data-i18n="active_status"' in ADMIN_HTML
    assert 'option value="disabled" data-i18n="status_disabled"' in ADMIN_HTML
    assert "statusFilter: document.querySelector" in ADMIN_HTML
    assert 'els.statusFilter.addEventListener("change", renderAgents)' in ADMIN_HTML
    assert "function agentStatus(agent)" in ADMIN_HTML
    assert 'agent.status === "disabled"' in ADMIN_HTML
    assert ".map(agent => ({agent, status: agentStatus(agent)}))" in ADMIN_HTML
    assert "index === 1" not in ADMIN_HTML
    assert "button:focus-visible" in ADMIN_HTML
    assert "button, input, select { min-height: 44px; }" in ADMIN_HTML
    assert 'id="modelsTableScroll" tabindex="0" role="region"' in ADMIN_HTML
    assert 'aria-describedby="modelsTableHint"' in ADMIN_HTML
    assert ADMIN_TRANSLATIONS["en"]["models_table_scroll_hint"].endswith(
        "review latency and success."
    )
    assert "no_agents_match" in ADMIN_HTML
    assert ADMIN_TRANSLATIONS["en"]["no_agents_match"] == (
        "No models match these filters. Clear a filter to see more models."
    )
    assert '{ pass: "ok", warn: "warning", fail: "failure" }[row.status]' in ADMIN_HTML
    assert ADMIN_TRANSLATIONS["en"]["readiness_ok"] == "Pass"
    assert ADMIN_TRANSLATIONS["ko"]["readiness_failure"] == "실패"
    assert ADMIN_TRANSLATIONS["en"]["readiness_summary_text"].startswith(
        "Sales and commercial criteria passed:"
    )
    assert ADMIN_TRANSLATIONS["ko"]["readiness_summary_text"].startswith("판매 및 상용 기준 통과")
    assert ADMIN_TRANSLATIONS["en"]["measurement_local_runtime_snapshot"] == "Measured on this server"
    assert ADMIN_TRANSLATIONS["ko"]["measurement_local_runtime_snapshot"] == "이 서버에서 측정됨"
    assert 'return t("measurement_local_runtime")' in ADMIN_HTML
    assert 't("spend_no_price_action")' in ADMIN_HTML
    assert "${escapeHtml(statusLabel(" in ADMIN_HTML
    assert "<strong>${statusLabel(" not in ADMIN_HTML
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
    assert ADMIN_TRANSLATIONS["en"]["session_action"] == (
        "Session required — open Integrations to sign in"
    )
    assert 'id="sessionAction"' in ADMIN_HTML
    assert "els.sessionAction.hidden = false" in ADMIN_HTML
    assert "if (res.ok && els.sessionAction) els.sessionAction.hidden = false" in ADMIN_HTML
    assert 'els.sessionAction?.addEventListener("click", () => showView("integrations"))' in ADMIN_HTML
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
    assert "Field encryption and audited release" not in ADMIN_HTML


def test_model_group_mutations_refresh_audit_events() -> None:
    """Model-group mutations refresh the shared Audit view."""
    assert "async function refreshAuditEvents()" in ADMIN_HTML
    assert "async function refreshModelGroupViews()" in ADMIN_HTML
    assert 'state.recent_audit_events = payload.recent_audit_events || [];' in ADMIN_HTML
    assert "renderAudit();" in ADMIN_HTML
    assert 'apiFetch("/admin/state")' in ADMIN_HTML
    assert "await refreshModelGroupViews();" in ADMIN_HTML
    assert "async function deleteModelGroup(groupName)" in ADMIN_HTML
    assert "audit_refresh_warning" in ADMIN_TRANSLATIONS["en"]
    assert "model_groups_refresh_warning" in ADMIN_TRANSLATIONS["ko"]

    def source_between(start_marker: str, end_marker: str) -> str:
        start_index = ADMIN_HTML.index(start_marker)
        end_index = ADMIN_HTML.index(end_marker, start_index)
        # Parenthesize so eval() yields the function value (a bare function
        # declaration statement has no completion value of its own).
        return "(" + ADMIN_HTML[start_index:end_index].strip() + ")"

    node_script = "\n".join(
        [
            'import assert from "node:assert/strict";',
            f"const refreshModelGroups = eval({json.dumps(source_between('async function refreshModelGroups()', '    async function refreshAuditEvents'))});",
            f"const refreshAuditEvents = eval({json.dumps(source_between('async function refreshAuditEvents()', '    function showModelGroupRefreshWarning'))});",
            f"const showModelGroupRefreshWarning = eval({json.dumps(source_between('function showModelGroupRefreshWarning(message)', '    async function refreshModelGroupViews'))});",
            f"const refreshModelGroupViews = eval({json.dumps(source_between('async function refreshModelGroupViews()', '    async function saveModelGroup'))});",
            f"const saveModelGroup = eval({json.dumps(source_between('async function saveModelGroup(event)', '    function renderTrace(result)'))});",
            f"const deleteModelGroup = eval({json.dumps(source_between('async function deleteModelGroup(groupName)', '    els.modelGroups.addEventListener'))});",
            "let queuedResponses = [];",
            "const calls = [];",
            "const renderEvents = [];",
            'const state = {modelGroups: [], agents: [], recent_audit_events: []};',
            'const els = {modelGroupName: {value: "release-group"}, modelGroupMembers: {selectedOptions: [{value: "agent-one"}]}, modelGroupFeedback: {textContent: "", style: {}}};',
            'const messages = {group_saved: "Group saved.", group_deleted: "Group deleted.", audit_refresh_warning: "Audit refresh warning.", model_groups_refresh_warning: "Groups refresh warning."};',
            "function t(key) { return messages[key] || key; }",
            "function renderModelGroups() { renderEvents.push(\"groups\"); }",
            "function renderAudit() { renderEvents.push(\"audit\"); }",
            "function makeResponse(ok, status, payload, rejectJson = false) { return {ok, status, async json() { if (rejectJson) throw new Error(\"malformed response\"); return payload; }}; }",
            "function setScenario(...responses) { queuedResponses = responses.slice(); calls.length = 0; renderEvents.length = 0; els.modelGroupFeedback.textContent = \"\"; els.modelGroupFeedback.style = {}; }",
            "globalThis.fetch = async function(url, options = {}) { calls.push({url, method: options.method || \"GET\"}); const next = queuedResponses.shift(); assert.ok(next, \"handler requested an unexpected response\"); if (next instanceof Error) throw next; return next; };",
            "globalThis.apiFetch = async function(url, options) { return globalThis.fetch(url, options); };",
            "setScenario(makeResponse(true, 201, {group_name: \"release_group\"}), makeResponse(true, 200, {items: []}), makeResponse(false, 503, {error: {message: \"temporarily unavailable\"}}));",
            "await saveModelGroup({preventDefault() {}});",
            "assert.match(els.modelGroupFeedback.textContent, /Group saved\\./);",
            "assert.match(els.modelGroupFeedback.textContent, /Audit refresh warning\\./);",
            "assert.equal(els.modelGroupFeedback.style.color, \"var(--amber)\");",
            "assert.deepEqual(calls.map(({url, method}) => [url, method]), [[\"/api/v1/model_groups\", \"POST\"], [\"/api/v1/model_groups\", \"GET\"], [\"/admin/state\", \"GET\"]]);",
            "setScenario(makeResponse(true, 201, {group_name: \"release_group\"}), makeResponse(true, 200, {items: []}), new Error(\"connection reset\"));",
            "await saveModelGroup({preventDefault() {}});",
            "assert.match(els.modelGroupFeedback.textContent, /Group saved\\./);",
            "assert.match(els.modelGroupFeedback.textContent, /Audit refresh warning\\./);",
            "assert.equal(els.modelGroupFeedback.style.color, \"var(--amber)\");",
            "setScenario(makeResponse(true, 200, {deleted: true}), makeResponse(true, 200, {items: []}), makeResponse(true, 200, null, true));",
            "await deleteModelGroup(\"release-group\");",
            "assert.match(els.modelGroupFeedback.textContent, /Group deleted\\./);",
            "assert.match(els.modelGroupFeedback.textContent, /Audit refresh warning\\./);",
            "assert.equal(els.modelGroupFeedback.style.color, \"var(--amber)\");",
            "assert.deepEqual(calls.map(({url, method}) => [url, method]), [[\"/api/v1/model_groups/release-group\", \"DELETE\"], [\"/api/v1/model_groups\", \"GET\"], [\"/admin/state\", \"GET\"]]);",
        ]
    )
    completed = subprocess.run(
        [shutil.which("node") or "node", "--input-type=module"],
        input=node_script,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr + completed.stdout


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
    test_model_group_mutations_refresh_audit_events()
    test_admin_state_exposes_agents_without_secrets()
    print("ok")
