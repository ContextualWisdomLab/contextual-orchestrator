# NIM benchmark security-integration receipt

## Status

This record binds the evidence-grade NVIDIA NIM benchmark to the provider-egress
security base without treating an older pull-request head as current approval
evidence. It is an architecture decision record and verification receipt, not a
release declaration or production routing recommendation.

## Current review identity

The current review target is:

- benchmark head `48f007d9ec0ace3c1bcaee9b99236929fd622a4b`;
- stacked provider-egress base `03124cf97b7bf02e30a48a13acfd78b6ef08d1ef`;
- pull request `ContextualWisdomLab/contextual-orchestrator#90`.

No workflow run or approval is recorded here as current-head acceptance evidence.
The latest head includes a test-first Atheris instrumentation repair and must
obtain fresh exact-head checks and independent review before readiness changes.

## Historical integration evidence

The following identifiers are retained only as historical integration evidence.
They must not be used as current approval, branch-protection, or merge evidence:

- benchmark source head `9b72816bb61fa540b8eb20fdc559e740a3c3c6ec`;
- provider-egress security head `03124cf97b7bf02e30a48a13acfd78b6ef08d1ef`;
- resulting historical integration commit
  `a2af3634d67a361cac18ba11ff9b8db24417b646`; and
- historical integration workflow run `31005510483`.

The benchmark remains stacked on the provider-egress security branch until that
branch reaches protected `main`. Every later head or base change invalidates
prior checks and approvals automatically.

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
8. Evidence below the configured task and completion floors reports
   `insufficient_evidence` and cannot authorize a production routing change.

## Historical verification evidence

Historical integration commit `a2af3634d67a361cac18ba11ff9b8db24417b646`
was recorded as passing:

- 449 repository tests;
- 111 focused NIM tests;
- 982 production statements at 100% coverage;
- 374 production branches at 100% coverage;
- 100% public-docstring coverage;
- Python compilation;
- wheel build, isolated installation, and import; and
- `git diff --check`.

That historical run had one reviewed conflict, in `CHANGELOG.md`. Its
deterministic resolution retained both the NIM complete-request-plan evidence
and the security base's APA 7 environment-marker doctoring entry. These results
do not establish the status of current head `48f007d9ec0ace3c1bcaee9b99236929fd622a4b`.

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
