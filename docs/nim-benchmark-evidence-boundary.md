# NVIDIA NIM benchmark evidence boundary

Issue #86 requires evidence before production routing can change. This first
slice freezes task and scorer identities, requires complete run provenance, and
publishes JSON, CSV, Markdown, and provenance as one replaceable directory.

It deliberately performs no scoring, uncertainty, vector, Pareto, or routing
arithmetic. Those calculations remain a later Rust-owned slice. A dry-run
artifact proves only schema and publication behavior; it does not prove model
quality, cost, or production readiness.

The implementation reuses the valid transactional design from closed PR #90,
but its checks, reviews, and runtime evidence are not transferred. It corrects
that branch's duplicate CSV-field defect by keeping this slice independent of
CSV enrichment.

Operators must supply these exact non-empty artifacts:

- `benchmark_report.json`
- `benchmark_cells.csv`
- `benchmark_summary.md`
- `run_provenance.json`

The provenance object accepts only the protected Git source identity, catalog
and task-manifest SHA-256 identities, pricing-scenario SHA-256 or the explicit
value `unknown`, plus workflow-run and evidence status. Unexpected fields fail
closed so secrets cannot be silently serialized.
