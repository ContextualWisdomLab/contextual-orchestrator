---
id: "0043"
title: "Declare workflow depth and output-token budgets"
status: proposed
proposed_date: "2026-09-07"
deciders:
  - "repository maintainer"
affected_components:
  - "contextual_orchestrator/nim_benchmark.py"
related:
  - path: "docs/planning/adrs/0042-declared-paired-bootstrap-coverage.md"
    relation: extends
success_criteria:
  - metric: "no hidden workflow envelope"
    target: "omitted maximum_calls or max_workflow_depth fails closed"
    source: "tests/test_nim_benchmark.py::test_planned_evaluation_requests_require_declared_maximum_calls"
  - metric: "no hidden output-token cap"
    target: "omitted max_output_tokens fails closed; CLI cannot invent 264"
    source: "tests/test_nim_benchmark.py::test_run_benchmark_requires_declared_workflow_budget"
---

# ADR 0043: Declare workflow depth and output-token budgets

- Status: Proposed
- Date: 2026-09-07
- Doctoring record: [`docs/doctoring/nim-benchmark-evidence-grade.md`](../../doctoring/nim-benchmark-evidence-grade.md)

## Product requirement

A buyer comparing `route` and `conduct` needs to know the equal-call envelope
and the per-call output cap that bounded every cell. A hidden five-step
workflow and a 264-token output default allocate evaluation compute without an
operator declaration. Those numbers may still be chosen for a run; they cannot
live as code defaults.

## Decision

In the context of NIM equal-budget policy evidence, facing repository-authored
`MAX_WORKFLOW_DEPTH = 5` and `DEFAULT_MAX_OUTPUT_TOKENS = 264`, we chose
required declarations and against restoring those constants, to keep the
compute envelope reconstructible, accepting that a run without flags fails
closed.

`planned_evaluation_requests`, `plan_complete_request_budget`,
`evaluate_policies`, and `run_benchmark` take `maximum_calls` /
`max_workflow_depth` and `max_output_tokens` / `total_token_budget` as
required positive integers. `None` is a fail-closed sentinel. The equal cell
token budget is the product of the two declarations. CLI flags
`--max-workflow-depth` and `--max-output-tokens` have no hidden default.
Workflow YAML and tests may still write 5 and 264 as this run's choices.

Report schema stays 4.0.0; those fields already exist in provenance and are
now validated as declarations. Production route/conduct defaults stay locked.
The psychometric held-out harness's 2,000-sample 95% interval is the
successor slice in ADR 0044.

## Alternatives considered

- Keep 5 and 264 as module constants. Rejected: they hide the evaluation
  envelope from the report consumer and from CLI callers who omit flags.
- Derive depth from Conductor/TRINITY paper claims. Rejected: those papers
  motivate a bounded deep path; they do not authorize this repository to pick
  five as a silent default.
- Change production `OrchestrationPolicy.max_workflow_steps`. Rejected:
  `production_default_change_allowed` remains false.

## Consequences

Positive: request planning, equal-budget cells, and provenance all use the
same declared envelope.

Negative: existing CLI, workflow, and library callers must pass the
declarations; omitting them fails closed.

## Remaining work

Held-out bootstrap coverage moves to ADR 0044. This ADR is Proposed until
independent review and protected delivery.
