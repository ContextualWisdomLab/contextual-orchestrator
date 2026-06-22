ADMIN_TRANSLATIONS = {
    "en": {
        "brand_name": "Contextual Orchestrator",
        "nav_overview": "Overview",
        "nav_agent_pool": "Agent Pool",
        "nav_orchestration": "Orchestration",
        "nav_evaluations": "Evaluations",
        "nav_datasets": "Datasets",
        "nav_access_control": "Access Control",
        "nav_integrations": "Integrations",
        "nav_observability": "Observability",
        "nav_audit": "Audit",
        "nav_settings": "Settings",
        "environment_label": "Environment",
        "region_label": "Region",
        "language_label": "Language",
        "healthy_status": "Healthy",
        "active_status": "Active",
        "agent_pool_title": "Agent Pool",
        "register_agent": "Register Agent",
        "search_agents": "Search agents",
        "all_statuses": "All statuses",
        "orchestration_policy": "Orchestration Policy",
        "simulation_title": "Simulation",
        "run_trace": "Run Trace",
        "live_workflow_trace": "Live Workflow Trace",
        "view_json": "View JSON",
        "audit_compliance": "Audit & Compliance",
        "recent_errors": "Recent Errors",
        "source_basis": "Source basis",
        "source_basis_text": "Fugu: one interface. TRINITY: thinker, worker, verifier. Conductor: access-list workflow visibility.",
        "agent_header": "Agent",
        "model_header": "Model",
        "tags_header": "Tags",
        "status_header": "Status",
        "capacity_header": "Capacity",
        "success_header": "Success",
        "status_healthy": "Healthy",
        "status_degraded": "Degraded",
        "latency_threshold": "Latency P95 route threshold",
        "workflow_hints": "Workflow trigger hints",
        "verifier_required": "Verifier required",
        "agent_exclusion": "Agent exclusion policy",
        "timeline_tab": "Timeline",
        "access_list_tab": "Access List",
        "json_tab": "JSON",
        "rule_header": "Rule",
        "scope_header": "Scope",
        "exclusion_header": "Exclusion",
        "view_all": "View all",
        "route_degradation": "Route degradation",
        "verifier_disagreement": "Verifier disagreement",
        "agent_capacity": "Agent capacity",
        "worker_latency": "worker exceeded latency threshold",
        "confidence_low": "confidence below policy threshold",
        "planner_capacity": "planner pool near soft limit",
    },
    "ko": {
        "brand_name": "컨텍스트 오케스트레이터",
        "nav_overview": "개요",
        "nav_agent_pool": "에이전트 풀",
        "nav_orchestration": "오케스트레이션",
        "nav_evaluations": "평가",
        "nav_datasets": "데이터셋",
        "nav_access_control": "접근 제어",
        "nav_integrations": "연동",
        "nav_observability": "관측",
        "nav_audit": "감사",
        "nav_settings": "설정",
        "environment_label": "환경",
        "region_label": "리전",
        "language_label": "언어",
        "healthy_status": "정상",
        "active_status": "활성",
        "agent_pool_title": "에이전트 풀",
        "register_agent": "에이전트 등록",
        "search_agents": "에이전트 검색",
        "all_statuses": "전체 상태",
        "orchestration_policy": "오케스트레이션 정책",
        "simulation_title": "시뮬레이션",
        "run_trace": "트레이스 실행",
        "live_workflow_trace": "실시간 워크플로 트레이스",
        "view_json": "JSON 보기",
        "audit_compliance": "감사 및 컴플라이언스",
        "recent_errors": "최근 오류",
        "source_basis": "논문 근거",
        "source_basis_text": "Fugu: 단일 인터페이스. TRINITY: thinker, worker, verifier. Conductor: access-list 기반 워크플로 가시성.",
        "agent_header": "에이전트",
        "model_header": "모델",
        "tags_header": "태그",
        "status_header": "상태",
        "capacity_header": "용량",
        "success_header": "성공률",
        "status_healthy": "정상",
        "status_degraded": "저하",
        "latency_threshold": "라우팅 P95 지연 임계값",
        "workflow_hints": "워크플로 트리거 힌트",
        "verifier_required": "검증 단계 필수",
        "agent_exclusion": "에이전트 제외 정책",
        "timeline_tab": "타임라인",
        "access_list_tab": "접근 목록",
        "json_tab": "JSON",
        "rule_header": "규칙",
        "scope_header": "범위",
        "exclusion_header": "제외 항목",
        "view_all": "전체 보기",
        "route_degradation": "라우팅 성능 저하",
        "verifier_disagreement": "검증 불일치",
        "agent_capacity": "에이전트 용량",
        "worker_latency": "worker 지연 임계값 초과",
        "confidence_low": "신뢰도가 정책 임계값보다 낮음",
        "planner_capacity": "planner 풀이 소프트 한도에 근접",
    },
}


ADMIN_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="icon" href="data:,">
  <title>Contextual Orchestrator Admin</title>
  <style>
    :root {
      --bg: #f7f8f7;
      --surface: #ffffff;
      --surface-2: #f1f4f3;
      --line: #dfe5e3;
      --text: #1c2524;
      --muted: #62706d;
      --teal: #087f7a;
      --teal-soft: #dff4f1;
      --amber: #b96f00;
      --amber-soft: #fff2d8;
      --red: #c9362c;
      --green: #198754;
      --shadow: 0 10px 30px rgba(24, 37, 35, .07);
      --r: 6px;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font: 14px/1.45 "Aptos", "Segoe UI", sans-serif;
      letter-spacing: 0;
    }
    button, input, select, textarea { font: inherit; }
    .app { min-height: 100vh; display: grid; grid-template-columns: 248px 1fr; }
    .sidebar {
      background: var(--surface);
      border-right: 1px solid var(--line);
      display: flex;
      flex-direction: column;
    }
    .brand {
      height: 56px;
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 0 18px;
      border-bottom: 1px solid var(--line);
      font-weight: 700;
      font-size: 17px;
    }
    .mark {
      width: 24px;
      height: 24px;
      border-radius: 50%;
      background: conic-gradient(from 20deg, var(--teal), #56b8a8, #1c2524, var(--teal));
    }
    nav { padding: 10px; display: grid; gap: 3px; }
    .nav-item {
      border: 0;
      background: transparent;
      color: #33413f;
      min-height: 38px;
      border-radius: var(--r);
      display: grid;
      grid-template-columns: 26px 1fr;
      align-items: center;
      width: 100%;
      text-align: left;
      padding: 0 10px;
      cursor: pointer;
    }
    .nav-item[aria-current="page"], .nav-item:hover { background: var(--surface-2); color: var(--text); }
    .side-footer { margin-top: auto; padding: 14px 16px; color: var(--muted); font-size: 12px; border-top: 1px solid var(--line); }
    .main { min-width: 0; }
    .topbar {
      height: 56px;
      background: var(--surface);
      border-bottom: 1px solid var(--line);
      display: flex;
      align-items: center;
      gap: 22px;
      padding: 0 18px;
    }
    .field { display: flex; align-items: center; gap: 8px; color: var(--muted); }
    select, input, textarea {
      border: 1px solid var(--line);
      border-radius: var(--r);
      background: var(--surface);
      color: var(--text);
      min-height: 34px;
      padding: 0 10px;
    }
    textarea { min-height: 72px; padding: 10px; resize: vertical; width: 100%; }
    .health {
      margin-left: auto;
      color: var(--green);
      background: #e7f6ec;
      padding: 5px 10px;
      border-radius: 999px;
      font-weight: 650;
    }
    .language-switch { margin-left: 6px; }
    .grid {
      display: grid;
      grid-template-columns: minmax(640px, 1.25fr) minmax(330px, .75fr);
      gap: 12px;
      padding: 12px;
    }
    .panel {
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: var(--r);
      box-shadow: var(--shadow);
      min-width: 0;
      align-self: start;
    }
    .panel-header {
      min-height: 48px;
      padding: 12px 14px;
      border-bottom: 1px solid var(--line);
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
    }
    h1, h2, h3 { margin: 0; line-height: 1.2; }
    h1 { font-size: 18px; }
    h2 { font-size: 15px; }
    h3 { font-size: 13px; color: var(--muted); font-weight: 700; text-transform: uppercase; }
    .actions { display: flex; gap: 8px; align-items: center; }
    .btn {
      border: 1px solid var(--line);
      background: var(--surface);
      color: var(--text);
      border-radius: var(--r);
      min-height: 34px;
      padding: 0 10px;
      cursor: pointer;
    }
    .btn.primary { background: var(--teal); color: white; border-color: var(--teal); }
    .btn:hover { filter: brightness(.98); }
    .toolbar {
      padding: 12px 14px;
      display: flex;
      gap: 10px;
      border-bottom: 1px solid var(--line);
    }
    .toolbar input { min-width: 240px; }
    table { width: 100%; border-collapse: collapse; }
    th, td { padding: 10px 12px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; font-size: 13px; }
    th { color: var(--muted); font-weight: 650; background: #fbfcfc; }
    .dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; margin-right: 8px; background: var(--green); }
    .dot.warn { background: var(--amber); }
    .chip {
      display: inline-flex;
      align-items: center;
      min-height: 22px;
      padding: 0 7px;
      border-radius: 999px;
      background: var(--surface-2);
      color: #465450;
      font-size: 12px;
      margin: 0 4px 4px 0;
    }
    .chip.green { background: #e7f6ec; color: var(--green); }
    .chip.amber { background: var(--amber-soft); color: var(--amber); }
    .bar { width: 90px; height: 4px; border-radius: 999px; background: #d9eeeb; overflow: hidden; margin-top: 5px; }
    .bar span { display: block; height: 100%; background: var(--teal); }
    .split { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
    .policy-list { padding: 12px 14px; display: grid; gap: 9px; }
    .metric { display: grid; grid-template-columns: 1fr auto; padding: 8px 0; border-bottom: 1px solid var(--line); }
    .metric.source { grid-template-columns: 1fr; gap: 4px; }
    .metric.source strong { font-weight: 600; line-height: 1.4; }
    .workflow { grid-column: 1 / 2; }
    .trace { padding: 16px 14px; }
    .steps {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 10px;
      align-items: stretch;
    }
    .step {
      border: 1px solid var(--line);
      border-radius: var(--r);
      padding: 12px;
      background: #fbfcfc;
      min-height: 116px;
    }
    .step strong { display: block; margin-bottom: 4px; }
    .step small { color: var(--muted); }
    .access {
      margin-top: 10px;
      display: flex;
      gap: 5px;
      flex-wrap: wrap;
    }
    .tabs { display: flex; gap: 14px; border-bottom: 1px solid var(--line); padding: 0 14px; }
    .tab {
      border: 0;
      background: transparent;
      padding: 12px 0;
      color: var(--muted);
      cursor: pointer;
      border-bottom: 2px solid transparent;
    }
    .tab.active { color: var(--teal); border-bottom-color: var(--teal); }
    .json {
      margin: 0;
      padding: 14px;
      background: #10201e;
      color: #d9fbf5;
      overflow: auto;
      min-height: 190px;
      font: 12px/1.5 "Cascadia Mono", "SFMono-Regular", monospace;
    }
    .json[hidden] { display: none; }
    .audit { display: grid; gap: 12px; }
    .audit { align-self: start; align-content: start; }
    .audit-list { padding: 10px 14px 14px; display: grid; gap: 10px; }
    .event {
      display: grid;
      grid-template-columns: 24px 1fr auto;
      gap: 8px;
      align-items: start;
      padding: 8px 0;
      border-bottom: 1px solid var(--line);
    }
    .event b { font-size: 13px; }
    .event small { color: var(--muted); }
    .status-icon {
      width: 20px;
      height: 20px;
      border-radius: 50%;
      display: grid;
      place-items: center;
      color: white;
      background: var(--red);
      font-size: 12px;
      font-weight: 800;
    }
    .status-icon.warn { background: var(--amber); }
    @media (max-width: 980px) {
      .app { grid-template-columns: 1fr; }
      .sidebar { display: none; }
      .grid { grid-template-columns: minmax(0, 1fr); max-width: 100vw; overflow: hidden; }
      .panel { max-width: calc(100vw - 24px); overflow-x: auto; }
      table { min-width: 560px; }
      .workflow { grid-column: auto; }
      .steps { grid-template-columns: 1fr; }
      .toolbar { flex-wrap: wrap; }
      .toolbar input { min-width: 0; width: 100%; }
      .topbar { flex-wrap: wrap; height: auto; min-height: 56px; padding: 10px; }
      .topbar { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
      .health { margin-left: 0; justify-self: start; }
      .field { min-width: 0; }
      select { max-width: 100%; }
    }
  </style>
</head>
<body>
  <div class="app">
    <aside class="sidebar">
      <div class="brand"><span class="mark"></span><span data-i18n="brand_name">Contextual Orchestrator</span></div>
      <nav aria-label="Admin navigation">
        <button class="nav-item" aria-current="page"><span>⌂</span><span data-i18n="nav_overview">Overview</span></button>
        <button class="nav-item"><span>▦</span><span data-i18n="nav_agent_pool">Agent Pool</span></button>
        <button class="nav-item"><span>⌁</span><span data-i18n="nav_orchestration">Orchestration</span></button>
        <button class="nav-item"><span>◫</span><span data-i18n="nav_evaluations">Evaluations</span></button>
        <button class="nav-item"><span>▣</span><span data-i18n="nav_datasets">Datasets</span></button>
        <button class="nav-item"><span>□</span><span data-i18n="nav_access_control">Access Control</span></button>
        <button class="nav-item"><span>◇</span><span data-i18n="nav_integrations">Integrations</span></button>
        <button class="nav-item"><span>⌕</span><span data-i18n="nav_observability">Observability</span></button>
        <button class="nav-item"><span>§</span><span data-i18n="nav_audit">Audit</span></button>
        <button class="nav-item"><span>⚙</span><span data-i18n="nav_settings">Settings</span></button>
      </nav>
      <div class="side-footer">Contextual Orchestrator v0.1.0</div>
    </aside>
    <main class="main">
      <header class="topbar">
        <div class="field"><span data-i18n="environment_label">Environment</span><select><option>prod-us-east-1</option><option>staging</option></select></div>
        <div class="field"><span data-i18n="region_label">Region</span><strong>US East</strong></div>
        <div class="field language-switch"><span data-i18n="language_label">Language</span><select id="language"><option value="en">English</option><option value="ko">한국어</option></select></div>
        <div class="health">● <span data-i18n="healthy_status">Healthy</span></div>
      </header>
      <section class="grid">
        <section class="panel">
          <div class="panel-header">
            <h1><span data-i18n="agent_pool_title">Agent Pool</span> <span id="agentCount" class="chip"></span></h1>
            <div class="actions"><button class="btn primary">+ <span data-i18n="register_agent">Register Agent</span></button><button class="btn" aria-label="Agent settings">⚙</button></div>
          </div>
          <div class="toolbar">
            <input id="agentSearch" type="search" placeholder="Search agents" data-i18n-placeholder="search_agents">
            <select id="statusFilter"><option data-i18n="all_statuses">All statuses</option><option>Healthy</option><option>Degraded</option></select>
          </div>
          <table>
            <thead>
              <tr><th data-i18n="agent_header">Agent</th><th data-i18n="model_header">Model</th><th data-i18n="tags_header">Tags</th><th data-i18n="status_header">Status</th><th data-i18n="capacity_header">Capacity</th><th data-i18n="success_header">Success</th></tr>
            </thead>
            <tbody id="agents"></tbody>
          </table>
        </section>
        <section class="panel">
          <div class="panel-header">
            <h2 data-i18n="orchestration_policy">Orchestration Policy</h2>
            <span class="chip green" data-i18n="active_status">Active</span>
          </div>
          <div class="policy-list">
            <div>
              <h3 data-i18n="simulation_title">Simulation</h3>
              <textarea id="prompt">Analyze the architecture, implement the code, and verify risks.</textarea>
              <div class="actions" style="margin-top:8px">
                <select id="mode"><option value="auto">auto</option><option value="route">route</option><option value="conduct">conduct</option></select>
                <button class="btn primary" id="run" data-i18n="run_trace">Run Trace</button>
              </div>
            </div>
            <div class="metric source"><span data-i18n="source_basis">Source basis</span><strong data-i18n="source_basis_text">Fugu: one interface. TRINITY: thinker, worker, verifier. Conductor: access-list workflow visibility.</strong></div>
            <div class="metric"><span data-i18n="latency_threshold">Latency P95 route threshold</span><strong>2.50s</strong></div>
            <div class="metric"><span data-i18n="workflow_hints">Workflow trigger hints</span><strong id="hintCount">0</strong></div>
            <div class="metric"><span data-i18n="verifier_required">Verifier required</span><strong>Yes</strong></div>
            <div class="metric"><span data-i18n="agent_exclusion">Agent exclusion policy</span><strong>Config</strong></div>
          </div>
        </section>
        <section class="panel workflow">
          <div class="panel-header">
            <h2 data-i18n="live_workflow_trace">Live Workflow Trace</h2>
            <div class="actions"><span id="traceMode" class="chip green">Live</span><button class="btn" id="copyJson" data-i18n="view_json">View JSON</button></div>
          </div>
          <div class="trace">
            <div class="steps" id="steps"></div>
          </div>
          <div class="tabs">
            <button class="tab active" data-tab="timeline" data-i18n="timeline_tab">Timeline</button>
            <button class="tab" data-tab="access" data-i18n="access_list_tab">Access List</button>
            <button class="tab" data-tab="json" data-i18n="json_tab">JSON</button>
          </div>
          <pre class="json" id="traceJson" hidden></pre>
        </section>
        <aside class="audit">
          <section class="panel">
            <div class="panel-header"><h2 data-i18n="audit_compliance">Audit &amp; Compliance</h2><span class="chip">4 rules</span></div>
            <table>
              <thead><tr><th data-i18n="rule_header">Rule</th><th data-i18n="scope_header">Scope</th><th data-i18n="exclusion_header">Exclusion</th></tr></thead>
              <tbody>
                <tr><td>PII-001</td><td>All agents</td><td>Mask email, phone</td></tr>
                <tr><td>SEC-002</td><td>worker</td><td>Tool web_search</td></tr>
                <tr><td>DATA-003</td><td>verifier</td><td>Field ip_address</td></tr>
                <tr><td>FIN-004</td><td>synthesizer</td><td>Record amount</td></tr>
              </tbody>
            </table>
          </section>
          <section class="panel">
            <div class="panel-header"><h2 data-i18n="recent_errors">Recent Errors</h2><button class="btn" data-i18n="view_all">View all</button></div>
            <div class="audit-list">
              <div class="event"><span class="status-icon warn">!</span><div><b data-i18n="route_degradation">Route degradation</b><br><small data-i18n="worker_latency">worker exceeded latency threshold</small></div><small>2m</small></div>
              <div class="event"><span class="status-icon">!</span><div><b data-i18n="verifier_disagreement">Verifier disagreement</b><br><small data-i18n="confidence_low">confidence below policy threshold</small></div><small>11m</small></div>
              <div class="event"><span class="status-icon warn">!</span><div><b data-i18n="agent_capacity">Agent capacity</b><br><small data-i18n="planner_capacity">planner pool near soft limit</small></div><small>18m</small></div>
            </div>
          </section>
        </aside>
      </section>
    </main>
  </div>
  <script>
    const translations = __TRANSLATIONS__;
    const els = {
      agents: document.querySelector("#agents"),
      agentCount: document.querySelector("#agentCount"),
      agentSearch: document.querySelector("#agentSearch"),
      hintCount: document.querySelector("#hintCount"),
      prompt: document.querySelector("#prompt"),
      mode: document.querySelector("#mode"),
      run: document.querySelector("#run"),
      steps: document.querySelector("#steps"),
      traceJson: document.querySelector("#traceJson"),
      traceMode: document.querySelector("#traceMode"),
      language: document.querySelector("#language")
    };
    let state = {agents: [], last: null};
    let currentLang = "en";

    function t(key) {
      return (translations[currentLang] || translations.en)[key] || translations.en[key] || key;
    }

    function tags(tags) {
      return tags.map(tag => `<span class="chip">${tag}</span>`).join("");
    }
    function renderAgents() {
      const q = els.agentSearch.value.toLowerCase();
      const rows = state.agents.filter(agent => agent.id.toLowerCase().includes(q) || agent.model.toLowerCase().includes(q));
      els.agentCount.textContent = `${rows.length} agents`;
      els.agents.innerHTML = rows.map((agent, index) => `
        <tr>
          <td><span class="dot ${index === 1 ? "warn" : ""}"></span><strong>${agent.id}</strong><br><small>${agent.base_url}</small></td>
          <td>${agent.model}</td>
          <td>${tags(agent.tags)}</td>
          <td><span class="chip ${index === 1 ? "amber" : "green"}">${index === 1 ? t("status_degraded") : t("status_healthy")}</span></td>
          <td><div>${72 - index * 8}%</div><div class="bar"><span style="width:${72 - index * 8}%"></span></div></td>
          <td>${(99.2 - index * .4).toFixed(1)}%</td>
        </tr>`).join("");
    }
    function renderTrace(result) {
      els.traceMode.textContent = result.mode;
      const trace = result.trace || [];
      els.steps.innerHTML = trace.map(step => `
        <article class="step">
          <strong>${step.role}</strong>
          <small>${step.agent_id}</small>
          <p>${step.subtask || "Direct route"}</p>
          <div class="access">${(step.access || []).map(id => `<span class="chip">Step ${id}</span>`).join("") || '<span class="chip">No prior access</span>'}</div>
        </article>`).join("");
      els.traceJson.textContent = JSON.stringify(result, null, 2);
    }
    function applyI18n(lang) {
      const dict = translations[lang] || translations.en;
      currentLang = translations[lang] ? lang : "en";
      document.documentElement.lang = lang;
      document.querySelectorAll("[data-i18n]").forEach(node => {
        const key = node.getAttribute("data-i18n");
        if (dict[key]) node.textContent = dict[key];
      });
      document.querySelectorAll("[data-i18n-placeholder]").forEach(node => {
        const key = node.getAttribute("data-i18n-placeholder");
        if (dict[key]) node.setAttribute("placeholder", dict[key]);
      });
      localStorage.setItem("admin_lang", lang);
      if (state.agents.length) renderAgents();
    }
    async function load() {
      const res = await fetch("/admin/state");
      state = await res.json();
      els.hintCount.textContent = state.policy.complex_hints.length;
      renderAgents();
      await simulate();
    }
    async function simulate() {
      const res = await fetch("/admin/simulate", {
        method: "POST",
        headers: {"content-type": "application/json"},
        body: JSON.stringify({prompt: els.prompt.value, mode: els.mode.value})
      });
      state.last = await res.json();
      renderTrace(state.last);
    }
    els.agentSearch.addEventListener("input", renderAgents);
    els.run.addEventListener("click", simulate);
    els.language.addEventListener("change", () => applyI18n(els.language.value));
    document.querySelector("#copyJson").addEventListener("click", () => {
      els.traceJson.hidden = !els.traceJson.hidden;
      if (!els.traceJson.hidden) navigator.clipboard?.writeText(els.traceJson.textContent);
    });
    document.querySelectorAll(".tab").forEach(tab => tab.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach(item => item.classList.remove("active"));
      tab.classList.add("active");
      els.traceJson.hidden = tab.dataset.tab !== "json";
    }));
    const initialLang = new URLSearchParams(location.search).get("lang") || localStorage.getItem("admin_lang") || "en";
    els.language.value = translations[initialLang] ? initialLang : "en";
    applyI18n(els.language.value);
    load();
  </script>
</body>
</html>
""".replace("__TRANSLATIONS__", __import__("json").dumps(ADMIN_TRANSLATIONS, ensure_ascii=False))
