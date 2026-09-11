from __future__ import annotations

import json
import shutil
import subprocess

from contextual_orchestrator.admin import ADMIN_HTML


def _source_between(start_marker: str, end_marker: str) -> str:
    """Return one embedded JavaScript function as an evaluable expression."""
    start_index = ADMIN_HTML.index(start_marker)
    end_index = ADMIN_HTML.index(end_marker, start_index)
    return "(" + ADMIN_HTML[start_index:end_index].strip() + ")"


def test_model_group_mutations_refresh_agent_assignments_without_reload() -> None:
    """A committed group mutation must refresh agent assignment state in-place."""
    node_script = "\n".join(
        [
            'import assert from "node:assert/strict";',
            f"const refreshModelGroups = eval({json.dumps(_source_between('async function refreshModelGroups()', '    async function refreshAuditEvents'))});",
            f"const refreshAuditEvents = eval({json.dumps(_source_between('async function refreshAuditEvents()', '    function showModelGroupRefreshWarning'))});",
            f"const showModelGroupRefreshWarning = eval({json.dumps(_source_between('function showModelGroupRefreshWarning(message)', '    async function refreshModelGroupViews'))});",
            f"const refreshModelGroupViews = eval({json.dumps(_source_between('async function refreshModelGroupViews()', '    async function saveModelGroup'))});",
            f"const saveModelGroup = eval({json.dumps(_source_between('async function saveModelGroup(event)', '    function renderTrace(result)'))});",
            f"const deleteModelGroup = eval({json.dumps(_source_between('async function deleteModelGroup(groupName)', '    els.modelGroups.addEventListener'))});",
            "let queuedResponses = [];",
            "const renderAgentSnapshots = [];",
            'const state = {modelGroups: [], agents: [{id: "agent-one", model: "model-one", group_name: "old_group"}], recent_audit_events: []};',
            'const els = {modelGroupName: {value: "release-group"}, modelGroupMembers: {selectedOptions: [{value: "agent-one"}]}, modelGroupFeedback: {textContent: "", style: {}}};',
            'const messages = {group_saved: "Group saved.", group_deleted: "Group deleted.", audit_refresh_warning: "Audit refresh warning.", model_groups_refresh_warning: "Groups refresh warning."};',
            "function t(key) { return messages[key] || key; }",
            "function renderModelGroups() {}",
            "function renderAudit() {}",
            "function renderAgents() { renderAgentSnapshots.push(state.agents.map(agent => ({id: agent.id, group_name: agent.group_name ?? null}))); }",
            "function makeResponse(ok, status, payload) { return {ok, status, async json() { return payload; }}; }",
            "function setScenario(...responses) { queuedResponses = responses.slice(); els.modelGroupFeedback.textContent = \"\"; els.modelGroupFeedback.style = {}; }",
            "globalThis.fetch = async function(url, options = {}) { const next = queuedResponses.shift(); assert.ok(next, `unexpected request ${options.method || \"GET\"} ${url}`); return next; };",
            "globalThis.apiFetch = async function(url, options) { return globalThis.fetch(url, options); };",
            "setScenario(",
            "  makeResponse(true, 201, {group_name: \"release_group\"}),",
            "  makeResponse(true, 200, {items: [{group_name: \"release_group\", member_agent_ids: [\"agent-one\"], capability_coverage: {}}]}),",
            "  makeResponse(true, 200, {agents: [{id: \"agent-one\", model: \"model-one\", group_name: \"release_group\"}], recent_audit_events: [{event_type: \"model_group.saved\"}]})",
            ");",
            "await saveModelGroup({preventDefault() {}});",
            "assert.equal(state.agents[0].group_name, \"release_group\", \"save must refresh the Models assignment without a page reload\");",
            "renderAgents();",
            "assert.equal(renderAgentSnapshots.at(-1)[0].group_name, \"release_group\");",
            "setScenario(",
            "  makeResponse(true, 200, {deleted: true}),",
            "  makeResponse(true, 200, {items: []}),",
            "  makeResponse(true, 200, {agents: [{id: \"agent-one\", model: \"model-one\", group_name: null}], recent_audit_events: [{event_type: \"model_group.deleted\"}]})",
            ");",
            "await deleteModelGroup(\"release-group\");",
            "assert.equal(state.agents[0].group_name, null, \"delete must refresh the Models assignment without a page reload\");",
            "renderAgents();",
            "assert.equal(renderAgentSnapshots.at(-1)[0].group_name, null);",
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
