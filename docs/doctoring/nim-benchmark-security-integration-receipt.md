# NIM benchmark security-integration receipt

## Status

This record binds the evidence-grade NVIDIA NIM benchmark to the provider-egress
security base without treating an older pull-request head as current approval
evidence. It is an architecture decision record and verification receipt, not a
release declaration or production routing recommendation.

## Decision

The benchmark remains stacked on the provider-egress security branch until that
branch reaches protected `main`. The NIM implementation is accepted for renewed
review only from the exact two-parent integration of:

- benchmark source head `9b72816bb61fa540b8eb20fdc559e740a3c3c6ec`;
- provider-egress security head `03124cf97b7bf02e30a48a13acfd78b6ef08d1ef`;
- resulting reviewed integration commit
  `a2af3634d67a361cac18ba11ff9b8db24417b646`; and
- exact integration workflow run `31005510483`.

Any later documentation-only retrigger commit inherits that exact source tree but
must still obtain fresh current-head checks and independent review. No prior
check, approval, or security result is promoted to the new head automatically.

## Preserved security invariants

The integrated tree must preserve all of these properties:

1. HTTPS provider sockets dial only validation-time globally routable addresses.
2. The original provider hostname remains the HTTP authority, TLS SNI value, and
   certificate-verification identity.
3. Redirects and ambient proxy routing cannot forward provider credentials.
4. Plain HTTP remains restricted to literal loopback integration targets.
5. Provider responses are bounded before materialization.
6. Importing `contextual_orchestrator` does not eagerly load the optional NIM
   adapter or monkey-patch runtime classes.
7. Dry benchmark execution receives no `NVIDIA_NIM_API_KEY`; the bounded live
   job alone owns the GitHub Secret binding.
8. `COPILOT_GITHUB_TOKEN` is not a supported benchmark or review credential.

## Preserved evaluation invariants

The integrated benchmark must also preserve these evidence properties:

1. `GET /v1/models` is the run-time inventory authority.
2. The complete request plan is calculated after discovery and before the first
   capability probe.
3. An undersized hard cap fails before partial model probing.
4. Every discovered model receives every required capability probe when the run
   proceeds.
5. Direct, route-once, conduct, and reviewed cheapest-worker cells receive the
   same total prompt-plus-completion token allowance and maximum-call envelope.
6. Actual free-to-caller access evidence and hypothetical paid pricing remain
   distinct, versioned evidence classes.
7. Unknown model prices remain `unknown`; no rate is inferred or invented.
8. Smoke-sized evidence reports `insufficient_evidence` and cannot authorize a
   production routing change.

## Exact verification evidence

The integrated source passed:

- 449 repository tests;
- 111 focused NIM tests;
- 982 production statements at 100% coverage;
- 374 production branches at 100% coverage;
- 100% public-docstring coverage;
- Python compilation;
- wheel build, isolated installation, and import; and
- `git diff --check`.

The merge had one reviewed conflict, in `CHANGELOG.md`. Its deterministic
resolution retained both the NIM complete-request-plan evidence and the security
base's APA 7 environment-marker doctoring entry.

## Current-head acceptance rule

This receipt does not satisfy branch protection by itself. After every head or
base change, repository Tests, Fuzz, Security, Security Scan, SAST Semgrep,
central coverage, OpenCode, Noema, Strix, CodeRabbit, packaging, and all other
required checks must rerun on the exact current head and base. A non-author
independent approval is mandatory. Queued, skipped, action-required, stale-head,
or failed results are not success.

After the security prerequisite merges, this branch must be retargeted to the
resulting protected `main` and revalidated without modifying the accepted source
behavior. Only then may the pull request become Ready for review.
