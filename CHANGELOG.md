# Changelog

All notable changes to Contextual Orchestrator are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Add an optional provider-neutral NVIDIA NIM benchmark harness that dynamically discovers the live `/v1/models` catalog, probes every discovered model under bounded concurrency and a complete hard request plan, and compares every eligible direct model, route-once, bounded-conduct, and reviewed pricing-scenario policy under equal total token and call envelopes.
- Add deterministic no-egress dry runs, valid media fixtures, secret-redacted transactional JSON/CSV/Markdown artifacts, complete role/agent/model assignment evidence, paired bootstrap uncertainty, evidence sufficiency, and quality-latency and reviewed-hypothetical-cost Pareto frontiers.
- Add validation-time public-address-pinned provider transport, original-host authority/SNI/certificate verification, redirect and ambient-proxy rejection, credential-forwarding prevention, 8 MiB response bounds, and live-secret isolation to the NIM benchmark path.
- Add versioned strict complete-answer scoring for locked tasks: finite full-response decimal comparison, NFC-normalized declared text alternatives with task-specific case semantics, explicit alias and prompt-disambiguation evidence, a 4,096-character pre-normalization input cap, zero-score handling for oversized or unrepresentable model output, fail-before-egress answer-key validation, derived-manifest provenance, and lazy optional-adapter activation.
- Add permanent benchmark contracts for 100% production statement/branch coverage, 100% public docstrings, fuzzing, package build/install/import, exact contributor-head workflows, evidence-status semantics, and release acceptance without automatic routing authorization.

### Security

- Restrict the private plain-HTTP provider seam to `localhost` or literal loopback IP addresses, reject URL userinfo before connection, dial directly without ambient proxy lookup, reject all redirect responses, and close failed resources deterministically.
- Pin each HTTPS provider connection to the exact public addresses approved during validation, preserve the original hostname for TLS verification, bypass environment proxy resolution, and reject redirects to close DNS-rebinding and credential-forwarding SSRF paths.
- Bound every provider response to 8 MiB of cumulative consumed bytes, including SSE iteration, reject oversized declared lengths before body consumption, fail closed on malformed or conflicting `Content-Length` and ambiguous `Content-Length` plus `Transfer-Encoding`, redact header-inspection failures, and never silently truncate an untrusted response.
- Integrate DNS-pinned provider dispatch directly into `ModelClient` so package import performs no optional-adapter monkey-patching or order-dependent class mutation.
- Reject provider hosts that resolve to any non-globally-routable address, including RFC 6598 shared address space, while retaining explicit multicast, private, loopback, link-local, and reserved-address protections.
- Document narrowly scoped Semgrep suppressions for parameter-bound database queries, the explicit development-only TLS verification opt-out, and provider URLs that pass the egress guard.

### Changed

- Pin Atheris by Python interpreter so the Python 3.11 fuzz job and the newer central coverage-evidence image both install a published, hash-locked wheel.
- Run repository Tests, Fuzz, and Security workflows for stacked pull requests targeting any branch, bind every checkout to the literal contributor-head SHA, and keep checkout credentials non-persistent so local evidence cannot silently become absent or synthetic-merge-only evidence.

### Documentation

- Add APA 7 doctoring for Python environment-marker semantics, Atheris artifact availability and hashes, and the supported-platform uncertainty boundary.
- Add provider-response resource-bound doctoring covering the 8 MiB fail-closed limit, HTTP framing preflight, bounded SSE reads, batch-output partitioning, incident handling, and operational rollback.
- Add pull-request exact-head workflow doctoring covering stacked-base support, contributor-head identity, untrusted-code execution, merge-tree separation, cancellation handling, and rollback.
- Record the CI trust boundary between generic coverage and native fuzz execution, including the evidence-preserving retry rule for branch-referenced reusable workflows.
