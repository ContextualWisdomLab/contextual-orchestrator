# Changelog

All notable changes to Contextual Orchestrator are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Add an optional provider-neutral NVIDIA NIM benchmark harness that dynamically discovers the live `/v1/models` catalog, probes every discovered model under bounded concurrency and a hard request cap, records machine-readable capability outcomes, and compares direct, route-once, bounded-conduct, and explicit pricing-scenario policies over a locked task manifest.
- Add deterministic no-egress benchmark dry runs, secret-redacted JSON/CSV/Markdown evidence artifacts, paired bootstrap uncertainty, quality-latency and quality-hypothetical-cost Pareto frontiers, all-modality catalog fuzzing, and a manually gated benchmark workflow.
- Add a validated deterministic one-frame H.264 MP4 probe fixture, complete preflight reservation for every discovered model-capability cell plus the full evaluation envelope, and a thirty-task locked manifest that reaches the declared paired-evidence floor without creating an automatic routing recommendation.
- Add direct benchmark quality gates for 100% production statement/branch coverage, 100% public docstrings, wheel build/install/import smoke testing, and optional-import isolation.

### Security

- Restrict the private plain-HTTP provider seam to `localhost` or literal loopback IP addresses, reject URL userinfo before connection, dial directly without ambient proxy lookup, reject all redirect responses, and close failed resources deterministically.
- Pin each HTTPS provider connection to the exact public addresses approved during validation, preserve the original hostname for TLS verification, bypass environment proxy resolution, and reject redirects to close DNS-rebinding and credential-forwarding SSRF paths.
- Integrate DNS-pinned provider dispatch directly into `ModelClient` so package import performs no optional-adapter monkey-patching or order-dependent class mutation.
- Reject provider hosts that resolve to any non-globally-routable address, including RFC 6598 shared address space, while retaining explicit multicast, private, loopback, link-local, and reserved-address protections.
- Document narrowly scoped Semgrep suppressions for parameter-bound database queries and the explicit development-only TLS verification opt-out.
- Remove the NIM benchmark's dynamic `urllib.request.urlopen` sink and compatibility monkeypatch path; live discovery, probes, and evaluation now use direct validation-time-address-pinned TLS with original-host SNI/certificate verification, no proxy lookup, no redirect following, and deterministic cleanup.
- Bound every NIM provider response to 8 MiB and fail closed before an oversized catalog, probe, or evaluation body can exhaust benchmark-runner memory.
- Split scheduled dry and live benchmark jobs so zero-egress dry runs never receive `NVIDIA_NIM_API_KEY`; only the bounded live benchmark step receives the GitHub Secret.
- Remove temporary branch-writing/source-export repair mechanisms and the optional benchmark monkeypatch module from the mergeable tree.
- Import the NIM catalog parser while Atheris import instrumentation is active, with an AST regression contract that prevents parser branches from silently losing coverage guidance.

### Changed

- Exclude zero-success benchmark policies from quality Pareto frontiers with explicit evidence labels, validate every Markdown-consumed report field before artifact writes, normalize excessive catalog JSON depth to the catalog domain error, preserve positive sub-second provider timeouts, make the standalone NIM test runner fixture-safe, and execute these review regressions inside the 100% branch-coverage gate.
- Expose a stable complete-run request planning view and align API, CLI, manual-workflow, and deterministic test caps with the locked thirty-task evidence floor, preserving fail-before-probe behavior.
- Fail closed after catalog discovery but before capability egress when the complete all-model probe and equal-budget evaluation plan cannot fit the configured hard request cap; the monthly 2,000-request ceiling covers the representative 127-model, thirty-task, seven-worker plan requiring 1,564 requests and still rejects larger plans before partial probing.
- Pin Atheris by Python interpreter so the Python 3.11 fuzz job and the newer central coverage-evidence image both install a published, hash-locked wheel.
- Record the reviewed current NVIDIA NIM General FAQ as expiring evidence for free Developer Program hosted-endpoint prototyping access, while keeping NVIDIA AI Enterprise production licensing and every hypothetical model rate explicitly separate.
- Require live hypothetical pricing scenarios to carry reviewed source, reviewer, review date, validity horizon, rate basis, uncertainty, and explicit rates; reject unreviewed, incomplete, future-dated, or expired price evidence before provider egress.
- Give direct, route-once, conduct, and reviewed cheapest-worker cells one equal total prompt-plus-completion token budget and one common five-call envelope, with configured-versus-observed evidence in every cell.
- Keep the optional NIM adapter lazy: importing the runtime package no longer imports the benchmark or mutates benchmark globals.
- Record immutable source-artifact digests and exact Git tree identity in the integration evidence so buyers and reviewers can reproduce the accepted benchmark source independently of transient workflow state.

### Documentation

- Add APA 7 doctoring for Python environment-marker semantics, Atheris artifact availability and hashes, the NIM benchmark validity boundary, the thirty-task evidence floor, and supported-platform uncertainty.
- Make the NIM security-integration receipt head-stable: GitHub pull-request metadata and exact-head Checks are authoritative, while older commit and workflow identifiers remain explicitly historical only.
- Clarify that the bundled thirty-task NIM manifest may reach `evidence_review_required` only when the paired-task and 90% completion floors are met; otherwise it remains `insufficient_evidence`, and no artifact changes production routing automatically.
