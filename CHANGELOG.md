# Changelog

All notable changes to Contextual Orchestrator are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Security

- Reject provider hosts that resolve to any non-globally-routable address, including RFC 6598 shared address space, while retaining explicit multicast, private, loopback, link-local, and reserved-address protections.
- Document narrowly scoped Semgrep suppressions for parameter-bound database queries, the explicit development-only TLS verification opt-out, and provider URLs that pass the egress guard.
- Separate the NVIDIA NIM development agent from the GitHub write credential on different runners; publish only a size-bounded, path-validated patch artifact after rejecting Git internals, symbolic links, submodules, and untrusted Git hooks.

### Changed

- Pin Atheris by Python interpreter so the Python 3.11 fuzz job and the newer central coverage-evidence image both install a published, hash-locked wheel.
- Add a pull-request-first hourly product-development loop that fails closed on open PRs and a missing `NVIDIA_NIM_API_KEY`, runs one bounded read-only OpenCode agent session against NVIDIA NIM, validates its candidate on a fresh credentialed runner, and opens exactly one pull request while leaving review and merge authority in the organization-central governance workflows.
