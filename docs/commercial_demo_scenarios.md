# Commercial Demo Scenarios

Runtime endpoint: `/api/v1/commercial_demo_scenarios/latest`.

This document defines the KRW 2,000,000,000 buyer demo packet for Contextual
Orchestrator as one enterprise orchestration control plane. The demo proves the
compatible inference API, operator/admin evidence surface, workflow trace,
access-list inspection, evaluation replay, analytics truthfulness, Figma review
path, buyer acceptance workflow, review-process policy, and packaging decision.

It is not a valuation guarantee, purchase commitment, signed order, legal
opinion, production compliance certificate, or revenue proof. Figma Code Connect is not used.
Review process is not a blocker unless a concrete security, API contract,
document, or product defect is found.

Do not create a separate library, Git submodule, or extracted package now. Keep
the product as a single repository and one deployable control plane until there
is a second product, independent release cadence, or security provenance trigger.

## Demo Narrative

The buyer story is: call the OpenAI-compatible endpoint, inspect the conducted
workflow trace, verify access-list evidence, replay the same buyer prompt,
review admin readiness, validate metric labels, review Figma/FigJam artifacts,
and make the buyer acceptance decision from one control plane.

| Step | Persona | Evidence type | Runtime endpoint |
| --- | --- | --- | --- |
| Compatible API smoke | Economic buyer | measured_local | `/v1/chat/completions` |
| Conducted workflow trace | Platform operator | measured_local | `/api/v1/workflow_runs` |
| Access-list inspection | Compliance reviewer | repository_and_runtime_artifact | `/api/v1/access_reports/{workflow_run_id}` |
| Evaluation replay | Quality reviewer | measured_local | `/api/v1/evaluation_runs` |
| Admin readiness console | Economic buyer | repository_and_runtime_artifact | `/admin` |
| Metric truthfulness | Compliance reviewer | measured_local | `/api/v1/analytics_snapshots/latest` |
| Figma stakeholder review | Stakeholder reviewer | figma_artifact | Figma design and FigJam board |
| Buyer acceptance decision | Economic buyer | repository_and_runtime_artifact | `/api/v1/commercial_buyer_acceptance_workflows/latest` |
| Production and buyer follow-ups | Economic buyer | proposed_until_buyer_specific | buyer environment |

## Runtime Shape

`TaskOrchestrator.commercial_demo_scenario_report()` returns:

- `demo_status`: `commercial_demo_ready`,
  `commercial_demo_ready_with_warnings`, or `commercial_demo_blocked`.
- `measurement_status`: `local_commercial_demo_scenarios`.
- `demo_narrative`: title, promise, and target personas.
- `demo_summary`: ready, warning, blocked, persona, endpoint, review-process,
  and Code Connect counts.
- `demo_steps`: the persona demo script with evidence type, runtime endpoints,
  action, and expected evidence for each step.
- `required_runtime_endpoints`: the runtime surfaces that must be available for
  the buyer demo.
- `related_runtime_reports`: completion scorecard, buyer acceptance workflow,
  and analytics snapshot status.
- `library_split_decision`: the Ponytail packaging decision.

The endpoint reuses `/api/v1/commercial_completion_scorecards/latest`,
`/api/v1/commercial_buyer_acceptance_workflows/latest`, `/api/v1/analytics_snapshots/latest`,
and `/admin/state`. Proposed production or buyer-specific inputs remain
warnings until supplied by the buyer or deployment environment.

## Demo Status Rules

Ready: `commercial_demo_ready` means all demo steps are ready and no production
or buyer-specific follow-ups remain open.

Warning: `commercial_demo_ready_with_warnings` means repo-local demo evidence is
ready while production, ROI, legal, support, or buyer-specific inputs remain
explicit warnings.

Blocked: `commercial_demo_blocked` means security failure, API contract
regression, document mismatch, runtime defect, missing local demo evidence, or
Code Connect usage blocks the demo.

## Plugin Responsibilities

- Product Design owns the admin-console story, persona flow, and demo evidence
  priorities.
- Figma owns the editable screen set and FigJam diagram. Artifact:
  `KRW 2B Commercial Demo Scenarios`.
- Superpowers owns the implementation plan and verification loop.
- Ponytail keeps the artifact set small and prevents premature library,
  submodule, or package extraction.
- Data Analytics owns the metric truthfulness model and the split between
  measured local evidence, proposed production metrics, and proposed
  buyer-specific metrics.
