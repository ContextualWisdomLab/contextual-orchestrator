"""Verify that refreshing assignments redraws the console without caller help."""

from __future__ import annotations

import json
import shutil
import subprocess

from contextual_orchestrator.admin import ADMIN_HTML


def test_assignment_refresh_renders_server_state_and_preserves_client_views() -> None:
    """Successful refresh renders assignments before audit and retains client views."""
    start_index = ADMIN_HTML.index("async function refreshAuditEvents()")
    end_index = ADMIN_HTML.index("    function showModelGroupRefreshWarning", start_index)
    refresh_source = ADMIN_HTML[start_index:end_index]
    node_script = "\n".join([
        'import assert from "node:assert/strict";',
        'const priorRun = {workflow_run_id: "retained-run"};',
        'const priorAnalytics = {request_count: 7};',
        'const priorReadiness = {status: "retained"};',
        'const state = {agents: [], recent_audit_events: [], last: priorRun, analytics: priorAnalytics, readiness: priorReadiness};',
        'const refreshedAgents = [{id: "assigned-worker", group_name: "saved_group"}];',
        'const refreshedAudit = [{event_type: "model_group.saved"}];',
        'const renderEvents = [];',
        'async function apiFetch(requestUrl) {',
        '  assert.equal(requestUrl, "/admin/state");',
        '  return {ok: true, async json() { return {agents: refreshedAgents, recent_audit_events: refreshedAudit}; }};',
        '}',
        'function renderAgents() {',
        '  assert.strictEqual(state.agents, refreshedAgents);',
        '  renderEvents.push("agents");',
        '}',
        'function renderAudit() {',
        '  assert.strictEqual(state.recent_audit_events, refreshedAudit);',
        '  renderEvents.push("audit");',
        '}',
        f'const refreshAssignments = eval({json.dumps("(" + refresh_source + ")")});',
        'assert.equal(await refreshAssignments(), true);',
        'assert.deepEqual(renderEvents, ["agents", "audit"]);',
        'assert.strictEqual(state.last, priorRun);',
        'assert.strictEqual(state.analytics, priorAnalytics);',
        'assert.strictEqual(state.readiness, priorReadiness);',
    ])
    completed_process = subprocess.run(
        [shutil.which("node") or "node", "--input-type=module"],
        input=node_script,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed_process.returncode == 0, completed_process.stderr + completed_process.stdout
