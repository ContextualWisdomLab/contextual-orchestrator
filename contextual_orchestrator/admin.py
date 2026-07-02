"""Embedded admin console assets and locale bundles for the orchestrator."""

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
        "view_label": "View",
        "healthy_status": "Healthy",
        "active_status": "Active",
        "agent_pool_title": "Agent Pool",
        "register_agent": "Register Agent",
        "search_agents": "Search agents",
        "all_statuses": "All statuses",
        "no_agents_match": "No agents match the current filters.",
        "no_agents_configured": "No agents are configured yet.",
        "orchestration_policy": "Orchestration Policy",
        "simulation_title": "Simulation",
        "run_trace": "Run Trace",
        "live_workflow_trace": "Live Workflow Trace",
        "view_json": "View JSON",
        "audit_compliance": "Audit & Compliance",
        "recent_errors": "Recent Errors",
        "datasets_title": "Datasets",
        "access_control_title": "Access Control",
        "integrations_title": "Integrations",
        "observability_title": "Observability",
        "settings_title": "Settings",
        "compatible_api_adoption": "Compatible API adoption",
        "trace_complete_workflow_rate": "Trace-complete workflow rate",
        "policy_safe_routing_rate": "Policy-safe routing rate",
        "route_versus_conduct_mix": "Route-versus-conduct mix",
        "evaluation_replay_usage": "Evaluation replay usage",
        "agent_health_coverage": "Agent health coverage",
        "provider_exclusion_miss_rate": "Provider exclusion miss rate",
        "locale_key_parity": "Locale key parity",
        "sales_readiness": "sales_readiness",
        "sales_readiness_title": "Sales Readiness",
        "sales_ready": "Sales ready",
        "pilot_ready_with_warnings": "Pilot ready with warnings",
        "not_ready": "Not ready",
        "readiness_pass": "Pass",
        "readiness_warn": "Warn",
        "readiness_fail": "Fail",
        "api_compatibility": "OpenAI-compatible API",
        "admin_evidence": "Operator evidence surface",
        "trace_evidence": "Workflow trace evidence",
        "security_posture": "Security posture",
        "analytics_truthfulness": "Analytics truthfulness",
        "locale_readiness": "Locale readiness",
        "provider_egress_safety": "Provider egress safety",
        "evaluation_replay": "Evaluation Replay",
        "run_evaluation": "Run Evaluation",
        "dataset_name": "Dataset",
        "dataset_owner": "Owner",
        "dataset_prompts": "Prompts",
        "access_inspector": "Access List Inspector",
        "step_header": "Step",
        "visible_context": "Visible Context",
        "provider_header": "Provider",
        "endpoint_header": "Endpoint",
        "policy_header": "Policy",
        "metric_header": "Metric",
        "value_header": "Value",
        "locale_bundle": "Locale Bundle",
        "safe_trace_default": "Trace hidden by default",
        "single_api_status": "OpenAI-compatible endpoint active",
        "no_trace": "Run a conduct trace to populate workflow evidence.",
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
        "evaluation_hint": "Replay prompts against route or conduct mode before policy rollout.",
        "golden_prompts": "Golden prompts",
        "security_reviews": "Security reviews",
        "research_tasks": "Research tasks",
        "production_ready": "Production ready",
        "policy_control": "Policy control",
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
        "view_label": "화면",
        "healthy_status": "정상",
        "active_status": "활성",
        "agent_pool_title": "에이전트 풀",
        "register_agent": "에이전트 등록",
        "search_agents": "에이전트 검색",
        "all_statuses": "전체 상태",
        "no_agents_match": "현재 필터와 일치하는 에이전트가 없습니다.",
        "no_agents_configured": "아직 구성된 에이전트가 없습니다.",
        "orchestration_policy": "오케스트레이션 정책",
        "simulation_title": "시뮬레이션",
        "run_trace": "트레이스 실행",
        "live_workflow_trace": "실시간 워크플로 트레이스",
        "view_json": "JSON 보기",
        "audit_compliance": "감사 및 컴플라이언스",
        "recent_errors": "최근 오류",
        "datasets_title": "데이터셋",
        "access_control_title": "접근 제어",
        "integrations_title": "연동",
        "observability_title": "관측",
        "settings_title": "설정",
        "compatible_api_adoption": "호환 API 사용량",
        "trace_complete_workflow_rate": "트레이스 완성 워크플로 비율",
        "policy_safe_routing_rate": "정책 안전 라우팅 비율",
        "route_versus_conduct_mix": "route/conduct 분포",
        "evaluation_replay_usage": "평가 리플레이 사용량",
        "agent_health_coverage": "에이전트 상태 커버리지",
        "provider_exclusion_miss_rate": "공급자 제외 누락률",
        "locale_key_parity": "로케일 키 일치율",
        "sales_readiness": "sales_readiness",
        "sales_readiness_title": "판매 준비도",
        "sales_ready": "판매 준비 완료",
        "pilot_ready_with_warnings": "주의 조건부 파일럿 가능",
        "not_ready": "준비 미완료",
        "readiness_pass": "통과",
        "readiness_warn": "주의",
        "readiness_fail": "실패",
        "api_compatibility": "OpenAI 호환 API",
        "admin_evidence": "운영자 근거 화면",
        "trace_evidence": "워크플로 트레이스 근거",
        "security_posture": "보안 자세",
        "analytics_truthfulness": "분석 지표 진실성",
        "locale_readiness": "로케일 준비도",
        "provider_egress_safety": "공급자 송신 안전성",
        "evaluation_replay": "평가 리플레이",
        "run_evaluation": "평가 실행",
        "dataset_name": "데이터셋",
        "dataset_owner": "담당",
        "dataset_prompts": "프롬프트",
        "access_inspector": "접근 목록 검사기",
        "step_header": "단계",
        "visible_context": "보이는 컨텍스트",
        "provider_header": "공급자",
        "endpoint_header": "엔드포인트",
        "policy_header": "정책",
        "metric_header": "지표",
        "value_header": "값",
        "locale_bundle": "로케일 번들",
        "safe_trace_default": "트레이스는 기본 숨김",
        "single_api_status": "OpenAI 호환 엔드포인트 활성",
        "no_trace": "conduct 트레이스를 실행하면 워크플로 근거가 채워집니다.",
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
        "evaluation_hint": "정책 롤아웃 전에 route 또는 conduct 모드로 프롬프트를 재생합니다.",
        "golden_prompts": "골든 프롬프트",
        "security_reviews": "보안 리뷰",
        "research_tasks": "리서치 태스크",
        "production_ready": "프로덕션 준비",
        "policy_control": "정책 제어",
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
    .mobile-nav {
      display: none;
      padding: 10px 12px;
      background: var(--surface);
      border-bottom: 1px solid var(--line);
      gap: 8px;
      align-items: center;
    }
    .mobile-nav label { color: var(--muted); white-space: nowrap; }
    .mobile-nav select { width: 100%; }
    .grid {
      display: grid;
      grid-template-columns: minmax(640px, 1.25fr) minmax(330px, .75fr);
      gap: 12px;
      padding: 12px;
    }
    .view[hidden] { display: none; }
    .detail-grid {
      padding: 12px;
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
    }
    .wide { grid-column: 1 / -1; }
    .panel {
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: var(--r);
      box-shadow: var(--shadow);
      min-width: 0;
      align-self: start;
      scroll-margin-top: 68px;
    }
    .panel:focus { outline: 2px solid rgba(43, 108, 176, .45); outline-offset: 2px; }
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
    .chip.red { background: #ffe8e5; color: var(--red); }
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
    .inspector {
      padding: 14px;
      display: grid;
      gap: 10px;
    }
    .inspector[hidden] { display: none; }
    .access-row {
      display: grid;
      grid-template-columns: 120px 1fr;
      gap: 10px;
      border: 1px solid var(--line);
      border-radius: var(--r);
      padding: 10px;
      background: #fbfcfc;
    }
    .empty {
      border: 1px dashed var(--line);
      border-radius: var(--r);
      padding: 18px;
      color: var(--muted);
      background: #fbfcfc;
    }
    .kpis {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
      padding: 14px;
    }
    .kpi {
      border: 1px solid var(--line);
      border-radius: var(--r);
      padding: 12px;
      background: #fbfcfc;
    }
    .kpi strong { display: block; font-size: 22px; margin-top: 5px; }
    .readiness {
      border-top: 1px solid var(--line);
      padding: 14px;
      display: grid;
      gap: 10px;
    }
    .readiness-grid {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
    }
    .readiness-row {
      border: 1px solid var(--line);
      border-radius: var(--r);
      background: #fbfcfc;
      padding: 10px;
      display: grid;
      gap: 6px;
      min-width: 0;
    }
    .readiness-row strong,
    .readiness-row small { overflow-wrap: anywhere; }
    .readiness-row small { color: var(--muted); }
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
      .mobile-nav { display: flex; }
      .grid { grid-template-columns: minmax(0, 1fr); max-width: 100vw; overflow: hidden; }
      .detail-grid { grid-template-columns: minmax(0, 1fr); }
      .panel { max-width: calc(100vw - 24px); overflow-x: auto; }
      .wide { grid-column: auto; }
      .kpis { grid-template-columns: 1fr; }
      .readiness-grid { grid-template-columns: 1fr; }
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
        <button class="nav-item" data-view="overview" aria-current="page"><span>⌂</span><span data-i18n="nav_overview">Overview</span></button>
        <button class="nav-item" data-view="overview" data-section="agent-pool"><span>▦</span><span data-i18n="nav_agent_pool">Agent Pool</span></button>
        <button class="nav-item" data-view="overview" data-section="orchestration-policy"><span>⌁</span><span data-i18n="nav_orchestration">Orchestration</span></button>
        <button class="nav-item" data-view="evaluations"><span>◫</span><span data-i18n="nav_evaluations">Evaluations</span></button>
        <button class="nav-item" data-view="datasets"><span>▣</span><span data-i18n="nav_datasets">Datasets</span></button>
        <button class="nav-item" data-view="access"><span>□</span><span data-i18n="nav_access_control">Access Control</span></button>
        <button class="nav-item" data-view="integrations"><span>◇</span><span data-i18n="nav_integrations">Integrations</span></button>
        <button class="nav-item" data-view="observability"><span>⌕</span><span data-i18n="nav_observability">Observability</span></button>
        <button class="nav-item" data-view="audit"><span>§</span><span data-i18n="nav_audit">Audit</span></button>
        <button class="nav-item" data-view="settings"><span>⚙</span><span data-i18n="nav_settings">Settings</span></button>
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
      <div class="mobile-nav">
        <label for="mobileView" data-i18n="view_label">View</label>
        <select id="mobileView" aria-label="Admin view">
          <option value="overview" data-i18n="nav_overview">Overview</option>
          <option value="evaluations" data-i18n="nav_evaluations">Evaluations</option>
          <option value="datasets" data-i18n="nav_datasets">Datasets</option>
          <option value="access" data-i18n="nav_access_control">Access Control</option>
          <option value="integrations" data-i18n="nav_integrations">Integrations</option>
          <option value="observability" data-i18n="nav_observability">Observability</option>
          <option value="audit" data-i18n="nav_audit">Audit</option>
          <option value="settings" data-i18n="nav_settings">Settings</option>
        </select>
      </div>
      <section class="grid view" data-view="overview">
        <section class="panel" id="agent-pool" tabindex="-1">
          <div class="panel-header">
            <h1><span data-i18n="agent_pool_title">Agent Pool</span> <span id="agentCount" class="chip"></span></h1>
            <div class="actions"><button class="btn primary" id="registerAgent">+ <span data-i18n="register_agent">Register Agent</span></button><button class="btn" id="agentSettings" aria-label="Agent settings">⚙</button></div>
          </div>
          <div class="toolbar">
            <input id="agentSearch" type="search" placeholder="Search agents" data-i18n-placeholder="search_agents">
            <select id="statusFilter"><option value="all" data-i18n="all_statuses">All statuses</option><option value="healthy" data-i18n="status_healthy">Healthy</option><option value="degraded" data-i18n="status_degraded">Degraded</option></select>
          </div>
          <table>
            <thead>
              <tr><th data-i18n="agent_header">Agent</th><th data-i18n="model_header">Model</th><th data-i18n="tags_header">Tags</th><th data-i18n="status_header">Status</th><th data-i18n="capacity_header">Capacity</th><th data-i18n="success_header">Success</th></tr>
            </thead>
            <tbody id="agents"></tbody>
          </table>
        </section>
        <section class="panel" id="orchestration-policy" tabindex="-1">
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
          <div class="inspector" id="accessPanel" hidden></div>
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
            <div class="panel-header"><h2 data-i18n="recent_errors">Recent Errors</h2><button class="btn" id="viewAudit" data-i18n="view_all">View all</button></div>
            <div class="audit-list">
              <div class="event"><span class="status-icon warn">!</span><div><b data-i18n="route_degradation">Route degradation</b><br><small data-i18n="worker_latency">worker exceeded latency threshold</small></div><small>2m</small></div>
              <div class="event"><span class="status-icon">!</span><div><b data-i18n="verifier_disagreement">Verifier disagreement</b><br><small data-i18n="confidence_low">confidence below policy threshold</small></div><small>11m</small></div>
              <div class="event"><span class="status-icon warn">!</span><div><b data-i18n="agent_capacity">Agent capacity</b><br><small data-i18n="planner_capacity">planner pool near soft limit</small></div><small>18m</small></div>
            </div>
          </section>
        </aside>
      </section>
      <section class="detail-grid view" data-view="evaluations" hidden>
        <section class="panel wide">
          <div class="panel-header"><h1 data-i18n="evaluation_replay">Evaluation Replay</h1><button class="btn primary" id="runEvaluation" data-i18n="run_evaluation">Run Evaluation</button></div>
          <div class="policy-list">
            <p data-i18n="evaluation_hint">Replay prompts against route or conduct mode before policy rollout.</p>
            <textarea id="evaluationPrompts">Review this pull request for security risk.
Summarize this research thread and verify claims.</textarea>
            <select id="evaluationMode"><option value="route">route</option><option value="conduct">conduct</option></select>
          </div>
          <table><thead><tr><th>Run</th><th>Mode</th><th>Prompts</th><th>Success</th></tr></thead><tbody id="evaluationRows"></tbody></table>
        </section>
      </section>
      <section class="detail-grid view" data-view="datasets" hidden>
        <section class="panel wide">
          <div class="panel-header"><h1 data-i18n="datasets_title">Datasets</h1><span class="chip" data-i18n="production_ready">Production ready</span></div>
          <table><thead><tr><th data-i18n="dataset_name">Dataset</th><th data-i18n="dataset_owner">Owner</th><th data-i18n="dataset_prompts">Prompts</th><th data-i18n="policy_header">Policy</th></tr></thead><tbody id="datasetRows"></tbody></table>
        </section>
      </section>
      <section class="detail-grid view" data-view="access" hidden>
        <section class="panel wide">
          <div class="panel-header"><h1 data-i18n="access_inspector">Access List Inspector</h1><span class="chip" id="accessRunId">No run</span></div>
          <div class="inspector" id="accessPage"></div>
        </section>
      </section>
      <section class="detail-grid view" data-view="integrations" hidden>
        <section class="panel wide">
          <div class="panel-header"><h1 data-i18n="integrations_title">Integrations</h1><span class="chip green" data-i18n="single_api_status">OpenAI-compatible endpoint active</span></div>
          <table><thead><tr><th data-i18n="provider_header">Provider</th><th data-i18n="endpoint_header">Endpoint</th><th data-i18n="policy_header">Policy</th></tr></thead><tbody id="integrationRows"></tbody></table>
        </section>
      </section>
      <section class="detail-grid view" data-view="observability" hidden>
        <section class="panel wide">
          <div class="panel-header"><h1 data-i18n="observability_title">Observability</h1><span class="chip green">Live</span></div>
          <div class="kpis" id="kpis"></div>
          <div class="readiness" id="salesReadiness" data-source="/api/v1/sales_readiness/latest"></div>
          <table><thead><tr><th>Workflow</th><th>Mode</th><th>Policy</th><th>Created</th></tr></thead><tbody id="runRows"></tbody></table>
        </section>
      </section>
      <section class="detail-grid view" data-view="audit" hidden>
        <section class="panel wide">
          <div class="panel-header"><h1 data-i18n="audit_compliance">Audit &amp; Compliance</h1><span class="chip">Evidence</span></div>
          <table><thead><tr><th>Event</th><th>Detail</th><th>Created</th></tr></thead><tbody id="auditRows"></tbody></table>
        </section>
      </section>
      <section class="detail-grid view" data-view="settings" hidden>
        <section class="panel">
          <div class="panel-header"><h1 data-i18n="settings_title">Settings</h1><span class="chip" data-i18n="policy_control">Policy control</span></div>
          <div class="policy-list">
            <div class="metric"><span data-i18n="locale_bundle">Locale Bundle</span><strong>en, ko</strong></div>
            <div class="metric"><span data-i18n="safe_trace_default">Trace hidden by default</span><strong>Yes</strong></div>
            <div class="metric"><span data-i18n="single_api_status">OpenAI-compatible endpoint active</span><strong>/v1/chat/completions</strong></div>
          </div>
        </section>
      </section>
    </main>
  </div>
  <script>
    const translations = __TRANSLATIONS__;
    const els = {
      agents: document.querySelector("#agents"),
      agentCount: document.querySelector("#agentCount"),
      agentSearch: document.querySelector("#agentSearch"),
      statusFilter: document.querySelector("#statusFilter"),
      hintCount: document.querySelector("#hintCount"),
      prompt: document.querySelector("#prompt"),
      mode: document.querySelector("#mode"),
      run: document.querySelector("#run"),
      steps: document.querySelector("#steps"),
      accessPanel: document.querySelector("#accessPanel"),
      accessPage: document.querySelector("#accessPage"),
      accessRunId: document.querySelector("#accessRunId"),
      traceJson: document.querySelector("#traceJson"),
      traceMode: document.querySelector("#traceMode"),
      evaluationPrompts: document.querySelector("#evaluationPrompts"),
      evaluationMode: document.querySelector("#evaluationMode"),
      evaluationRows: document.querySelector("#evaluationRows"),
      runEvaluation: document.querySelector("#runEvaluation"),
      datasetRows: document.querySelector("#datasetRows"),
      integrationRows: document.querySelector("#integrationRows"),
      kpis: document.querySelector("#kpis"),
      salesReadiness: document.querySelector("#salesReadiness"),
      runRows: document.querySelector("#runRows"),
      auditRows: document.querySelector("#auditRows"),
      viewAudit: document.querySelector("#viewAudit"),
      agentSettings: document.querySelector("#agentSettings"),
      registerAgent: document.querySelector("#registerAgent"),
      mobileView: document.querySelector("#mobileView"),
      language: document.querySelector("#language")
    };
    let state = {agents: [], last: null, analytics: null, readiness: null};
    let currentLang = "en";
    let activeTraceTab = "timeline";
    const datasets = [
      {name: "golden_prompts", owner: "AI product", prompts: 42, policy: "route + conduct"},
      {name: "security_reviews", owner: "Security", prompts: 28, policy: "conduct required"},
      {name: "research_tasks", owner: "Research", prompts: 35, policy: "verifier required"}
    ];

    function escapeHtml(value) {
      return String(value ?? "").replace(/[&<>"']/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[char]));
    }

    function t(key) {
      return (translations[currentLang] || translations.en)[key] || translations.en[key] || key;
    }

    function tags(tags) {
      return tags.map(tag => `<span class="chip">${escapeHtml(tag)}</span>`).join("");
    }
    function agentStatus(index) {
      return index === 1
        ? {key: "degraded", chip: "amber", dot: "warn", label: t("status_degraded")}
        : {key: "healthy", chip: "green", dot: "", label: t("status_healthy")};
    }
    function renderAgents() {
      const q = els.agentSearch.value.toLowerCase();
      const selectedStatus = els.statusFilter.value;
      const rows = state.agents
        .map((agent, index) => ({agent, index, status: agentStatus(index)}))
        .filter(({agent, status}) => (agent.id.toLowerCase().includes(q) || agent.model.toLowerCase().includes(q)) && (selectedStatus === "all" || status.key === selectedStatus));
      els.agentCount.textContent = `${rows.length} agents`;
      els.agents.innerHTML = rows.map(({agent, index, status}) => `
        <tr>
          <td><span class="dot ${status.dot}"></span><strong>${escapeHtml(agent.id)}</strong><br><small>${escapeHtml(agent.base_url)}</small></td>
          <td>${escapeHtml(agent.model)}</td>
          <td>${tags(agent.tags)}</td>
          <td><span class="chip ${status.chip}">${status.label}</span></td>
          <td><div>${72 - index * 8}%</div><div class="bar"><span style="width:${72 - index * 8}%"></span></div></td>
          <td>${(99.2 - index * .4).toFixed(1)}%</td>
        </tr>`).join("") || `<tr><td colspan="6" class="empty" data-i18n="no_agents_match">${t("no_agents_match")}</td></tr>`;
    }
    function renderTrace(result) {
      els.traceMode.textContent = result.mode;
      const trace = result.trace || [];
      els.steps.innerHTML = trace.map(step => `
        <article class="step">
          <strong>${escapeHtml(step.role)}</strong>
          <small>${escapeHtml(step.agent_id)}</small>
          <p>${escapeHtml(step.subtask || "Direct route")}</p>
          <div class="access">${(step.access || []).map(id => `<span class="chip">Step ${escapeHtml(id)}</span>`).join("") || '<span class="chip">No prior access</span>'}</div>
        </article>`).join("");
      if (!trace.length) {
        els.steps.innerHTML = `<div class="empty" data-i18n="no_trace">${t("no_trace")}</div>`;
      }
      renderAccess(trace);
      renderTraceTab(activeTraceTab);
      els.traceJson.textContent = JSON.stringify(result, null, 2);
    }
    function renderAccess(trace) {
      const rows = trace.length ? trace.map(step => `
        <div class="access-row">
          <strong>${t("step_header")} ${escapeHtml(step.id)}<br><small>${escapeHtml(step.role)}</small></strong>
          <div><b>${t("visible_context")}</b><br>${(step.access || []).map(id => `<span class="chip">Step ${escapeHtml(id)}</span>`).join("") || '<span class="chip">Original prompt only</span>'}</div>
        </div>`).join("") : `<div class="empty">${t("no_trace")}</div>`;
      els.accessPanel.innerHTML = rows;
      els.accessPage.innerHTML = rows;
      els.accessRunId.textContent = state.last?.workflow_run_id || "No run";
    }
    function renderTraceTab(name) {
      activeTraceTab = name;
      els.steps.hidden = name !== "timeline";
      els.accessPanel.hidden = name !== "access";
      els.traceJson.hidden = name !== "json";
    }
    function renderDatasets() {
      els.datasetRows.innerHTML = datasets.map(item => `
        <tr><td>${t(item.name)}</td><td>${escapeHtml(item.owner)}</td><td>${item.prompts}</td><td>${escapeHtml(item.policy)}</td></tr>
      `).join("");
    }
    function renderIntegrations() {
      els.integrationRows.innerHTML = state.agents.map(agent => `
        <tr><td>${escapeHtml(agent.provider_name || agent.id)}</td><td>${escapeHtml(agent.base_url)}</td><td>${(agent.provider_exclusions || []).map(escapeHtml).join(", ") || "Allowed"}</td></tr>
      `).join("") || `<tr><td colspan="3" class="empty" data-i18n="no_agents_configured">${t("no_agents_configured")}</td></tr>`;
    }
    function renderObservability() {
      const runs = state.recent_workflow_runs || [];
      const analytics = state.analytics || {};
      const metricRows = [...(analytics.kpis || []), ...(analytics.guardrails || [])];
      els.kpis.innerHTML = metricRows.map(metric => {
        const rawValue = metric.value_percent ?? metric.value ?? metric.numerator ?? 0;
        const suffix = metric.value_percent == null ? "" : "%";
        return `<div class="kpi"><span>${escapeHtml(t(metric.metric_name) || metric.label)}</span><strong>${escapeHtml(rawValue)}${suffix}</strong></div>`;
      }).join("") || [
        ["Workflow runs", runs.length],
        ["Enabled agents", state.agents.length],
        ["Verifier required", state.policy.verifier_required ? "Yes" : "No"]
      ].map(([label, value]) => `<div class="kpi"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`).join("");
      els.runRows.innerHTML = runs.map(run => `
        <tr><td>${escapeHtml(run.workflow_run_id)}</td><td>${escapeHtml(run.mode)}</td><td>${escapeHtml(run.policy_mode)}</td><td>${escapeHtml(run.created_at)}</td></tr>
      `).join("") || `<tr><td colspan="4">${t("no_trace")}</td></tr>`;
      renderReadiness();
    }
    function renderReadiness() {
      const readiness = state.readiness || {};
      const status = readiness.readiness_status || "not_ready";
      const statusClass = status === "sales_ready" ? "green" : status === "pilot_ready_with_warnings" ? "amber" : "red";
      const criteria = readiness.criteria || [];
      els.salesReadiness.innerHTML = `
        <div class="metric">
          <span data-i18n="sales_readiness_title">${t("sales_readiness_title")}</span>
          <strong><span class="chip ${statusClass}">${escapeHtml(t(status))}</span></strong>
        </div>
        <div class="readiness-grid">
          ${criteria.slice(0, 8).map(row => {
            const chip = row.status === "pass" ? "green" : row.status === "warn" ? "amber" : "red";
            return `<div class="readiness-row">
              <span class="chip ${chip}">${escapeHtml(t(`readiness_${row.status}`))}</span>
              <strong>${escapeHtml(t(row.criterion_name) || row.label)}</strong>
              <small>${escapeHtml(row.evidence)}</small>
            </div>`;
          }).join("")}
        </div>`;
    }
    function renderAudit() {
      const events = state.recent_audit_events || [];
      els.auditRows.innerHTML = events.map(event => `
        <tr><td>${escapeHtml(event.event_type)}</td><td><pre>${escapeHtml(JSON.stringify(event.event_detail))}</pre></td><td>${escapeHtml(event.created_at)}</td></tr>
      `).join("") || `<tr><td colspan="3">No audit events yet</td></tr>`;
    }
    function renderSecondaryViews() {
      if (!state.policy) return;
      renderDatasets();
      renderIntegrations();
      renderObservability();
      renderAudit();
      renderAccess(state.last?.trace || []);
    }
    function showView(name, activeItem, sectionId) {
      document.querySelectorAll(".view").forEach(view => view.hidden = view.dataset.view !== name);
      document.querySelectorAll(".nav-item").forEach(item => {
        item.removeAttribute("aria-current");
      });
      (activeItem || document.querySelector(`.nav-item[data-view="${name}"]`))?.setAttribute("aria-current", "page");
      els.mobileView.value = name;
      renderSecondaryViews();
      if (sectionId) {
        requestAnimationFrame(() => {
          const target = document.getElementById(sectionId);
          const reducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
          target?.scrollIntoView({block: "start", behavior: reducedMotion ? "auto" : "smooth"});
          target?.focus({preventScroll: true});
        });
      }
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
      if (state.policy) renderSecondaryViews();
    }
    async function load() {
      const res = await fetch("/admin/state");
      state = await res.json();
      await refreshAnalytics();
      await refreshReadiness();
      els.hintCount.textContent = state.policy.complex_hints.length;
      renderAgents();
      renderSecondaryViews();
      await simulate();
    }
    async function refreshAnalytics() {
      const analyticsRes = await fetch("/api/v1/analytics_snapshots/latest");
      state.analytics = await analyticsRes.json();
    }
    async function refreshReadiness() {
      const readinessRes = await fetch("/api/v1/sales_readiness/latest");
      state.readiness = await readinessRes.json();
    }
    async function simulate() {
      const res = await fetch("/admin/simulate", {
        method: "POST",
        headers: {"content-type": "application/json"},
        body: JSON.stringify({prompt: els.prompt.value, mode: els.mode.value, include_orchestration_trace: true})
      });
      state.last = await res.json();
      state.recent_workflow_runs = [state.last, ...(state.recent_workflow_runs || [])].slice(0, 8);
      await refreshAnalytics();
      await refreshReadiness();
      renderTrace(state.last);
      renderSecondaryViews();
    }
    async function runEvaluation() {
      const prompts = els.evaluationPrompts.value.split("\n").map(item => item.trim()).filter(Boolean);
      const res = await fetch("/api/v1/evaluation_runs", {
        method: "POST",
        headers: {"content-type": "application/json"},
        body: JSON.stringify({prompts, run_mode: els.evaluationMode.value, include_orchestration_trace: true})
      });
      const result = await res.json();
      els.evaluationRows.insertAdjacentHTML("afterbegin", `<tr><td>${escapeHtml(result.evaluation_run_id)}</td><td>${escapeHtml(result.mode)}</td><td>${escapeHtml(result.prompt_count)}</td><td>${escapeHtml(result.success_count)}</td></tr>`);
      await refreshAnalytics();
      await refreshReadiness();
      renderSecondaryViews();
    }
    els.agentSearch.addEventListener("input", renderAgents);
    els.statusFilter.addEventListener("change", renderAgents);
    els.run.addEventListener("click", simulate);
    els.runEvaluation.addEventListener("click", runEvaluation);
    els.viewAudit.addEventListener("click", () => showView("audit"));
    els.agentSettings.addEventListener("click", () => showView("settings"));
    els.registerAgent.addEventListener("click", () => showView("integrations"));
    els.language.addEventListener("change", () => applyI18n(els.language.value));
    els.mobileView.addEventListener("change", () => showView(els.mobileView.value));
    document.querySelector("#copyJson").addEventListener("click", () => {
      renderTraceTab("json");
      navigator.clipboard?.writeText(els.traceJson.textContent);
    });
    document.querySelectorAll(".tab").forEach(tab => tab.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach(item => item.classList.remove("active"));
      tab.classList.add("active");
      renderTraceTab(tab.dataset.tab);
    }));
    document.querySelectorAll(".nav-item").forEach(item => item.addEventListener("click", () => showView(item.dataset.view || "overview", item, item.dataset.section)));
    const initialLang = new URLSearchParams(location.search).get("lang") || localStorage.getItem("admin_lang") || "en";
    els.language.value = translations[initialLang] ? initialLang : "en";
    applyI18n(els.language.value);
    load();
  </script>
</body>
</html>
""".replace("__TRANSLATIONS__", __import__("json").dumps(ADMIN_TRANSLATIONS, ensure_ascii=False))
