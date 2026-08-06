# NIM benchmark CSV assignment-evidence and publication boundary

## Decision

The benchmark JSON report is the authoritative structured record for each
policy/task cell. The supported CLI composition root enriches
`benchmark_cells.csv` with one additional column, `models_used_json`, before it
publishes a success result. The column is deterministic compact JSON containing
only these required fields for every observed call:

- `step_id`
- `role`
- `agent_id`
- `model_id`

This closes an acquisition-evidence gap: the JSON report already retained exact
role and worker assignments, but the spreadsheet-oriented CSV silently omitted
them. A buyer reviewing latency, score, tokens, and cost in CSV could therefore
not reconstruct which model served each orchestration step without joining the
separate JSON artifact manually.

The supported CLI now treats JSON, CSV, and Markdown as one publication unit.
It asks the benchmark implementation to render and secret-scan all three files
inside a hidden sibling staging directory, enriches and validates the CSV there,
validates the complete directory, and only then moves the staged directory to
the requested public path. The success payload is withheld until publication
succeeds and reports only final, public artifact paths.

## Integrity contract

### Cell and assignment integrity

1. The JSON report must contain `evaluation.evaluation_cells` as a list.
2. Every JSON and CSV cell must have one non-empty `(policy_name, task_id)`
   identity, with no duplicates.
3. The JSON and CSV identity sets must match exactly.
4. Every `models_used` entry must contain non-empty step, role, agent, and model
   identifiers.
5. Assignment arrays are serialized with UTF-8, sorted object keys, and compact
   separators. Array order is preserved because it carries workflow-step order.
6. CSV enrichment uses a synchronized temporary file followed by same-directory
   replacement. Validation failure leaves the staged CSV untouched.

### Complete-set publication integrity

1. The final path must name a dedicated directory. A symbolic link, regular
   file, `.` path, or otherwise ambiguous target is rejected.
2. Benchmark rendering, report-schema validation, cost-evidence validation,
   secret scanning, Markdown rendering, and CSV assignment enrichment happen
   outside the final path.
3. The staged directory must contain exactly three non-empty regular files:
   `benchmark_report.json`, `benchmark_cells.csv`, and
   `benchmark_summary.md`. Symbolic-link artifacts and extra files are rejected.
4. The enriched CSV must contain `models_used_json` before publication.
5. A fresh-target failure leaves no visible final directory and removes hidden
   staging residue.
6. When replacing an existing complete set, the prior directory is first moved
   to a hidden same-filesystem backup. If ordinary publication fails, the prior
   set is restored byte-for-byte and staging/backup residue is removed.
7. On success, the new complete directory becomes the final path, the prior
   backup is removed, and the emitted JSON result contains only final paths.
8. Benchmark-process failures pass through unchanged. Enrichment, validation,
   or publication failures emit a bounded machine-readable
   `benchmark_failed_closed` result rather than the buffered success payload.

## Portable rollback and crash-window contract

Portable filesystems do not provide one atomic operation that replaces an
existing non-empty directory with another non-empty directory. Replacement
therefore requires two same-filesystem renames:

1. final directory to hidden backup;
2. hidden staging directory to final directory.

Ordinary exceptions between or after these operations are rolled back in the
same process. A process or host crash between the two renames can nevertheless
leave the final name absent and one hidden backup present. The next supported
CLI invocation removes abandoned staging directories and restores that sole
backup before starting benchmark work. Multiple backups are ambiguous evidence;
the CLI fails closed for operator review rather than guessing which set is
authoritative. This contract provides recoverable transactional publication,
not an unsupported claim of crash-atomic replacement on every filesystem.

## Security and optional-adapter boundary

The adapter does not accept credentials, open sockets, change routing, infer
prices, or mutate benchmark globals. The benchmark renderer performs its normal
credential-leak checks while writing the private staged files. Assignment
enrichment copies only already validated assignment fields from that staged,
secret-scanned JSON report. The adapter is imported only by the explicit
`nim-benchmark` CLI branch, preserving side-effect-free ordinary package import
and the optional-adapter boundary.

## Deliberate limits

- The JSON report remains authoritative. CSV is a loss-minimized projection for
  spreadsheet and data-warehouse consumers, not a replacement for nested JSON.
- The compact assignment value is deterministic JSON, but this implementation
  does not claim full JSON Canonicalization Scheme conformance.
- Programmatic callers that invoke `run_benchmark` directly receive the original
  renderer semantics and may call `enrich_benchmark_cell_csv` explicitly. The
  supported CLI and scheduled workflow provide complete-set transactional
  publication automatically.
- Crash recovery is invocation-driven; no background daemon is introduced.
- No release or routing recommendation is created from this transformation.

## Verification

`tests/test_nim_csv_evidence.py` and
`tests/test_nim_csv_evidence_edges.py` cover deterministic serialization,
idempotence, malformed report shapes, invalid assignment values, duplicate and
mismatched identities, missing CSV columns, invalid JSON, output-directory
parsing, benchmark-failure passthrough, success withholding, and fail-closed
enrichment.

`tests/test_nim_artifact_publication.py` and
`tests/test_nim_artifact_publication_edges.py` cover fresh-target failure, prior
set preservation, ordinary mid-publication rollback, crash-backup recovery,
ambiguous-backup rejection, staging and backup cleanup, target-path safety,
complete-directory shape validation, final-path result rewriting, and malformed
success-payload rejection. The dedicated NIM quality job includes all four test
modules in the 100% production statement and branch coverage and public-docstring
gates, then builds, installs, and imports the wheel.

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
