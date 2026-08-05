# Changelog

All notable changes to Contextual Orchestrator are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Security

- Reject provider hosts that resolve to any non-globally-routable address, including RFC 6598 shared address space, while retaining explicit multicast, private, loopback, link-local, and reserved-address protections.
- Document narrowly scoped Semgrep suppressions for parameter-bound database queries, the explicit development-only TLS verification opt-out, and provider URLs that pass the egress guard.
- Separate the NVIDIA NIM development agent from both GitHub write credentials and the NIM API key: OpenCode runs in a capability-dropped, read-only, internal-network-only container, while a fixed-upstream broker injects the secret under request, concurrency, body, response, redirect, and content-type limits.
- Bind every scheduled NIM broker request to one bounded, fully validated A/AAAA snapshot, reject any non-global or excessive answer set, retain the original hostname for HTTP authority and TLS verification, and retry only the approved pinned addresses so DNS rebinding cannot redirect the credential-bearing connection.
- Publish autonomous changes only through a fresh runner after rejecting special filesystem entries, oversized trees, Git internals, `.github/` policy mutations, ambiguous paths, symbolic links, submodules, untrusted Git hooks, and oversized patch artifacts.
- Keep the publisher's built-in `GITHUB_TOKEN` read-only and fail closed unless OIDC yields a short-lived OpenCode GitHub App token, ensuring an autonomous pull request triggers the repository's required checks instead of suppressing downstream workflows.

### Changed

- Pin Atheris by Python interpreter so the Python 3.11 fuzz job and the newer central coverage-evidence image both install a published, hash-locked wheel.
- Add a pull-request-first hourly product-development loop that fails closed on open PRs and a missing `NVIDIA_NIM_API_KEY`, runs one bounded OpenCode session through the credential-isolated NVIDIA NIM broker, and opens exactly one reviewed pull request while leaving review and merge authority in the organization-central governance workflows.
