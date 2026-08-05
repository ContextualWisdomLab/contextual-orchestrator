# Changelog

All notable changes to Contextual Orchestrator are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Add a transport-neutral, versioned model fallback policy that validates explicit cost tiers and deterministically exhausts eligible free candidates before any paid fallback.
- Filter fallback candidates by repository visibility, required capability, and configured credential name without retaining or serializing secret values.
- Add a standard-library CLI for immutable cross-repository workflow integration, with complete statement, branch, and public-docstring coverage for the fallback policy.

### Security

- Pin each HTTPS provider connection to the exact public addresses approved during validation, preserve the original hostname for TLS verification, bypass environment proxy resolution, and reject redirects to close DNS-rebinding and credential-forwarding SSRF paths.
- Reject provider hosts that resolve to any non-globally-routable address, including RFC 6598 shared address space, while retaining explicit multicast, private, loopback, link-local, and reserved-address protections.
- Remove fallback-policy environment-value inspection; trusted callers now declare only validated available credential names, and the policy CLI rejects the former secret-bearing environment selector.
- Document narrowly scoped Semgrep suppressions for parameter-bound database queries, the explicit development-only TLS verification opt-out, and provider URLs that pass the egress guard.

### Changed

- Pin Atheris by Python interpreter so the Python 3.11 fuzz job and the newer central coverage-evidence image both install a published, hash-locked wheel.

### Documentation

- Add APA 7 doctoring for Python environment-marker semantics, Atheris artifact availability and hashes, and the supported-platform uncertainty boundary.
