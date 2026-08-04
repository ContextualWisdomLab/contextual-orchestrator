# Changelog

All notable changes to Contextual Orchestrator are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Add an optional provider-neutral NVIDIA NIM benchmark harness that dynamically discovers the live `/v1/models` catalog, probes every discovered model under bounded concurrency and a hard request cap, records machine-readable capability outcomes, and compares direct, route-once, bounded-conduct, and explicit pricing-scenario policies over a locked task manifest.
- Add deterministic no-egress benchmark dry runs, secret-redacted JSON/CSV/Markdown evidence artifacts, paired bootstrap uncertainty, quality-latency and quality-hypothetical-cost Pareto frontiers, all-modality catalog fuzzing, and a manually gated benchmark workflow.

### Security

- Pin each HTTPS provider connection to the exact public addresses approved during validation, preserve the original hostname for TLS verification, bypass environment proxy resolution, and reject redirects to close DNS-rebinding and credential-forwarding SSRF paths.
- Reject provider hosts that resolve to any non-globally-routable address, including RFC 6598 shared address space, while retaining explicit multicast, private, loopback, link-local, and reserved-address protections.
- Document narrowly scoped Semgrep suppressions for parameter-bound database queries, the explicit development-only TLS verification opt-out, and provider URLs that pass the egress guard.

### Changed

- Pin Atheris by Python interpreter so the Python 3.11 fuzz job and the newer central coverage-evidence image both install a published, hash-locked wheel.
