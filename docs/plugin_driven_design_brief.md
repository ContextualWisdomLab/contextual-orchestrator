# Plugin-Driven Product Design Brief

## Purpose

Use Figma, Product Design, Superpowers, Ponytail, and Data Analytics to extend
Contextual Orchestrator as one enterprise orchestration control plane. The work
must not split the product into separate Fugu, TRINITY, or Conductor surfaces.
It should turn the existing docs and stdlib admin console into shareable design,
diagram, analytics, and implementation artifacts.

## Confirmed Design Brief

Product surface: the enterprise admin console for a single OpenAI-compatible
orchestration API.

Primary users:

- Platform operators who manage agent health, capacity, priority, and provider
  exclusions.
- AI product owners who tune route-versus-conduct policy and explain why a
  workflow used deeper orchestration.
- Compliance reviewers who need runtime evidence for access lists, provider
  exclusions, verifier outcomes, and synthesis decisions.
- Localization owners who review English and Korean operator copy.

Visual source: the existing repo docs and admin implementation, especially
`docs/screen_design.md`, `docs/product_planning.md`, `docs/rest_api_design.md`,
`docs/i18n_design.md`, and `contextual_orchestrator/admin.py`.

Interactivity level: static-to-lightly-interactive product design artifacts.
The Figma screens should be editable and concrete enough for review, while the
stdlib admin console remains the working implementation.

## Source Audit

The current product spine is already explicit:

- Single API adoption remains centered on `/v1/chat/completions`.
- Operator evidence is exposed through `/admin`, `/admin/state`, and
  `/api/v1/*` management endpoints.
- The admin console uses a restrained enterprise palette: background
  `#f7f8f7`, surface `#ffffff`, border `#dfe5e3`, text `#1c2524`, muted text
  `#62706d`, primary accent `#087f7a`, warning accent `#b96f00`, and 6px
  radius.
- The UI is intentionally table-first, with no nested cards and no decorative
  SaaS chrome.
- English and Korean bundles are implemented in `ADMIN_TRANSLATIONS`.

## Required Product Surfaces

| Surface | Review question it answers | Existing source |
|---|---|---|
| Overview dashboard | Is the orchestration layer healthy and is the compatible API active? | `docs/product_planning.md`, `ADMIN_HTML` |
| Agent pool | Which workers are available, degraded, excluded, or capacity-limited? | `docs/screen_design.md`, `/api/v1/agent_pools` |
| Orchestration policy | When does the product route fast versus conduct a deeper workflow? | `docs/rest_api_design.md`, `/api/v1/orchestration_policies/default_policy` |
| Workflow trace | Which role, worker, subtask, and verifier outcome produced this answer? | `docs/architecture.md`, `/api/v1/workflow_runs/{workflow_run_id}` |
| Access report | Which prior outputs were visible to each workflow step? | `docs/rest_api_design.md`, `/api/v1/access_reports/{workflow_run_id}` |
| Evaluation replay | What happens if prompts are replayed before a policy rollout? | `/api/v1/evaluation_runs` |
| Locale review | Can English and Korean operator copy be reviewed as a resource? | `docs/i18n_design.md`, `/api/v1/locale_bundles/{locale_code}` |

## Canonical Direction

Use the existing screen-design tokens as the canonical direction for editable
Figma production frames. The three Product Design directions are still useful as
comparison material, but the canonical implementation should remain:

- evidence-first, not marketing-led;
- table-first, not card-heavy;
- operationally dense, but with clear section grouping;
- bilingual-ready, with English labels in the main frame and Korean copy called
  out in locale-review frames;
- trace-centered, so policy, access, and verification evidence are visible near
  each other.

## Design QA Checklist

- Every visible surface maps to one product bet from `docs/product_planning.md`.
- No screen introduces billing, RBAC, learned routing, recursive topology, or a
  visual workflow builder as an MVP feature.
- Every frame has stable surface names matching repo resources such as
  `agent_pools`, `workflow_runs`, `access_reports`, `evaluation_runs`, and
  `locale_bundles`.
- Figma artifacts are editable frames and diagrams, not screenshot-only output.
- Code Connect is not used for discovery, metadata, or generation.
- English and Korean remain in scope for the operator experience.
