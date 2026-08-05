# NIM benchmark CSV assignment-evidence boundary

## Decision

The benchmark JSON report is the authoritative structured record for each
policy/task cell. The CLI composition root now enriches `benchmark_cells.csv`
with one additional column, `models_used_json`, before it publishes a success
result. The column is deterministic compact JSON containing only these required
fields for every observed call:

- `step_id`
- `role`
- `agent_id`
- `model_id`

This closes an acquisition-evidence gap: the JSON report already retained exact
role and worker assignments, but the spreadsheet-oriented CSV silently omitted
them. A buyer reviewing latency, score, tokens, and cost in CSV could therefore
not reconstruct which model served each orchestration step without joining the
separate JSON artifact manually.

## Integrity contract

Enrichment is fail-closed and atomic.

1. The JSON report must contain `evaluation.evaluation_cells` as a list.
2. Every JSON and CSV cell must have one non-empty `(policy_name, task_id)`
   identity, with no duplicates.
3. The JSON and CSV identity sets must match exactly.
4. Every `models_used` entry must contain non-empty step, role, agent, and model
   identifiers.
5. Assignment arrays are serialized with UTF-8, sorted object keys, and compact
   separators. Array order is preserved because it carries workflow-step order.
6. A temporary file is flushed and synchronized before an atomic replacement of
   the prior CSV. Validation failure leaves the prior CSV untouched.
7. The benchmark CLI buffers its success payload and emits it only after CSV
   enrichment succeeds. Benchmark failures pass through unchanged; enrichment
   failures emit a machine-readable `benchmark_failed_closed` result.

The adapter does not accept credentials, open sockets, change routing, infer
prices, or mutate benchmark globals. It is imported only by the explicit
`nim-benchmark` CLI branch, preserving side-effect-free package import and the
optional-adapter boundary.

## Deliberate limits

- The JSON report remains authoritative. CSV is a loss-minimized projection for
  spreadsheet and data-warehouse consumers, not a replacement for nested JSON.
- The compact assignment value is deterministic JSON, but this implementation
  does not claim full JSON Canonicalization Scheme conformance.
- Programmatic callers that invoke `run_benchmark` directly still receive the
  original artifacts and may call `enrich_benchmark_cell_csv` explicitly. The
  supported CLI and scheduled workflow invoke the enrichment automatically.
- No release or routing recommendation is created from this transformation.

## Verification

`tests/test_nim_csv_evidence.py` covers deterministic serialization,
idempotence, malformed report shapes, invalid assignment values, duplicate and
mismatched identities, missing CSV columns, invalid JSON, output-directory
parsing, benchmark-failure passthrough, success withholding, and fail-closed
enrichment. The dedicated NIM quality job includes the adapter and its tests in
the 100% statement/branch coverage and public-docstring gates, then imports it
from the built wheel.

## References

Bray, T. (2017). *The JavaScript Object Notation (JSON) data interchange format*
(RFC 8259). Internet Engineering Task Force. https://doi.org/10.17487/RFC8259

National Institute of Standards and Technology. (2022). *Secure software
development framework (SSDF) version 1.1: Recommendations for mitigating the
risk of software vulnerabilities* (NIST Special Publication 800-218).
https://doi.org/10.6028/NIST.SP.800-218

Shafranovich, Y. (2005). *Common format and MIME type for comma-separated values
(CSV) files* (RFC 4180). Internet Engineering Task Force.
https://doi.org/10.17487/RFC4180
