# Changelog

All notable changes to Contextual Orchestrator are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Security

- Restrict the private plain-HTTP provider seam to `localhost` or literal loopback IP addresses, reject URL userinfo before connection, dial directly without ambient proxy lookup, reject all redirect responses, and close failed resources deterministically.
- Pin each HTTPS provider connection to the exact public addresses approved during validation, preserve the original hostname for TLS verification, bypass environment proxy resolution, and reject redirects to close DNS-rebinding and credential-forwarding SSRF paths.
- Fail closed at the final pre-socket HTTPS boundary when a provider Bearer credential is missing or empty at dispatch time, so credential revocation after DNS validation cannot degrade into unauthenticated provider network egress.
- Bound every provider response to 8 MiB of cumulative consumed bytes, including SSE iteration, reject oversized declared lengths before body consumption, fail closed on malformed or conflicting `Content-Length` and ambiguous `Content-Length` plus `Transfer-Encoding`, redact header-inspection failures, and never silently truncate an untrusted response.
- Accept only the single HTTP/1.1 `chunked` provider `Transfer-Encoding` that the reviewed standard-library transport decodes, and fail closed on unsupported transfer codings or coding chains before application model-output parsing.
- Require a real provider streaming response to advertise the `text/event-stream` media type before any streamed body line is consumed, accepting media-type parameters but rejecting missing or incompatible types and redacting header-access failures.
- Reject malformed UTF-8 in accepted provider SSE streams with one stable redacted error, preventing provider-controlled decoder detail from crossing the transport trust boundary while preserving deterministic cleanup.
- Fail closed when an accepted OpenAI-compatible SSE provider stream contains malformed `data:` JSON or reaches EOF before its terminal `data: [DONE]` marker, preventing truncated model output from being accepted as successful orchestration evidence.
- Reject malformed UTF-8/JSON, duplicate object names, Python non-finite-number extensions, finite-syntax exponents that overflow Python floats to non-finite values, and non-object top-level values in validated structured provider responses before application parsing; canonicalize valid JSON and strict Batch JSON Lines so later decoder failures cannot retain the original provider document.
- Integrate DNS-pinned provider dispatch directly into `ModelClient` so package import performs no optional-adapter monkey-patching or order-dependent class mutation.
- Reject provider hosts that resolve to any non-globally-routable address, including RFC 6598 shared address space, while retaining explicit multicast, private, loopback, link-local, and reserved-address protections.
- Document narrowly scoped Semgrep suppressions for parameter-bound database queries, the explicit development-only TLS verification opt-out, and provider URLs that pass the egress guard.

### Changed

- Pin Atheris by Python interpreter so the Python 3.11 fuzz job and the newer central coverage-evidence image both install a published, hash-locked wheel.
- Run repository Tests, Fuzz, and Security workflows for stacked pull requests targeting any branch, bind every checkout to the literal contributor-head SHA, and keep checkout credentials non-persistent so local evidence cannot silently become absent or synthetic-merge-only evidence.

### Documentation

- Add an indexed continuation evidence appendix that preserves the original
  documentation audit, classifies exact-head, integration, review, and absent
  evidence, and records protected-main release gaps without promoting active
  pull requests to shipped authority.
- Separate durable requirement traceability from volatile SHA, workflow,
  review, and branch snapshots by moving the dated audit into an indexed
  evidence appendix and enforcing that boundary in documentation fitness tests.
- Align the canonical cost, access-grant, internationalization, research-license, coverage, failure-flow, credential-authority, and status contracts with exact-head automated review findings and machine-check them.
- Status-qualify the analytics, REST API, and internationalization guides, replacing legacy prototype labels and distinguishing current standalone paths from optional planned framework adoption.
- Align Claude and conductor guidance with the current provider-neutral product and status-qualified dependency-adoption boundary, removing legacy lab and internal gate names.
- Replace stale lab/prototype and internal-name language in library research with machine-checked current-stack and adoption-status boundaries for the stdlib HTTP/admin path and optional API/database extras.
- Correct the supporting product plan's enterprise-auth boundary: the standalone runtime has coarse admin/inference bearer scopes, not tenant-aware RBAC, while the host owns enterprise identity and tenancy.
- Remove the remaining stdlib-lab qualifier from spend observability and describe the evidence boundary as a standalone deployment without promoting local signals to billing or compliance evidence.
- Replace the competitor-centric README disclaimer with an affirmative independent-implementation, third-party-model-weight, proprietary-artifact, and provider-boundary statement for commercial provenance review.
- Replace legacy lab framing in the root README with the current buyer-facing provider-neutral orchestration-control-plane identity and local-deployment boundary.
- Add a canonical release, migration, and rollback guide that binds protected-source identity, reproducible build and artifact provenance, state migration, publication, rollback, and protected-main operational acceptance without presenting Draft evidence as shipped.
- Establish a canonical status-qualified product documentation graph spanning PRD, TRD, architecture, UML, ERD, ADRs, threat model, test strategy, operability, incident response, traceability, standards/research references, and machine-checked authority boundaries without promoting active or planned work as shipped.
- Add APA 7 doctoring for Python environment-marker semantics, Atheris artifact availability and hashes, and the supported-platform uncertainty boundary.
- Add provider-response resource-bound doctoring covering the 8 MiB fail-closed limit, HTTP framing preflight, `text/event-stream` media-type enforcement, bounded SSE reads, OpenAI-compatible `[DONE]` completion evidence, malformed-event and premature-EOF handling, batch-output partitioning, incident handling, and operational rollback.
- Add provider-stream UTF-8 doctoring grounding strict SSE/JSON decoding and redacted malformed-input handling in the WHATWG HTML Standard and RFC 8259, with verification, failure, rollback, and authority boundaries.
- Add provider-JSON trust-boundary doctoring grounding strict UTF-8 object decoding, duplicate-name and non-finite-number rejection, finite-runtime numeric enforcement for extreme exponents, Batch JSONL validation, redacted parser failures, request-path authority, operator recovery, and rollback in RFC 8259, current Python documentation, and the OpenAI Batch API contract.
- Add provider transfer-coding doctoring that distinguishes full RFC 9112 protocol validity from the product's intentionally narrower decoded `chunked` subset, with fail-closed compatibility and rollback guidance.
- Add provider-credential revocation doctoring covering the dispatch-time race, final pre-socket Bearer guard, operator recovery, compatibility boundary, rollback invariant, and current IETF HTTP/OAuth references.
- Add pull-request exact-head workflow doctoring covering stacked-base support, contributor-head identity, untrusted-code execution, merge-tree separation, cancellation handling, and rollback.
- Record the CI trust boundary between generic coverage and native fuzz execution, including the evidence-preserving retry rule for branch-referenced reusable workflows.
