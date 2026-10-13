# Experiential promotional charge measurement

## Goal and boundary

This opt-in operator probe measures one synthetic request without changing account
payment, privacy, overflow, routing, or production model-admission policy. It is
separate from issue #1347's SearXNG/MCP consumer integration and from provider
catalog synchronization. Catalog synchronization performs no inference and cannot
establish a billed charge.

A literal `free: true`, non-display promotion may coexist with a nonzero catalog
base tariff. Neither establishes the charge for a request. The probe retains these
three observations separately:

- `response_cost_usd`: completion `usage.cost`, when valid and available.
- `generation_total_cost_usd`: request-specific generation receipt `total_cost`.
- `ledger_charge_usd`: exactly attributed settled export `cost_usd`, documented as
  charged credits only. BYOK estimates and `real_cost_usd` are not substituted.

The completion, generation, and settled-export USD observations are serialized as
**decimal strings or null** (`schema_version: 2`), never binary JSON floats.
Provider JSON numeric literals use `Decimal` during parsing; finite, nonnegative
values retain their exact units in USD, including tiny nonzero amounts. Numeric
agreement and explicit zero use exact decimal comparison. A float supplied by a
non-HTTP test adapter can only retain the precision it already carried; the native
HTTP path does not convert money through float.

Missing, malformed, negative, nonfinite, unpriced, duplicated, uncorrelated, or
incompletely paginated evidence stays unknown. Explicit zero is accepted only from
one priced, exactly attributed settled row. A mismatch is reported, not averaged
away. One zero-charge sample does not prove future free requests or authorize
production admission.

## Safe execution

Merge through the existing protected reviews first. On protected `main`, manually
dispatch **Provider catalog sync** with `measure_experiential_billing=true` and an
explicit positive `experiential_response_max_bytes` (bytes per HTTP response).
There is deliberately no default budget: the operator must select it for the
runner's available resources, accounting for raw bytes, JSON decoding/object
allocation overhead and other process state. Missing/invalid admission fails
before any provider operation. This is a resource-admission control, not a
provider size guarantee, cost threshold, or evidence of free usage.
The opt-in input defaults to false. The probe and catalog sync use separate
job-level concurrency groups (`experiential-billing` and `provider-catalog-sync`),
with no cancellation or dependency between them. A stalled null-timeout probe
cannot hold the scheduled catalog lock. The probe still
requires the production environment, and runs only on the first Actions attempt.
Scheduled runs and PR code cannot run it. Runtime credentials come from the KV;
the organization secret `EXPERIENTAL_LABS_API_KEY` is environment transport only
for in-process bootstrap. No credential extraction is needed or permitted.

The request uses a fixed synthetic prompt plus the documented attribution field.
It sends no sampling or output-token parameter: the provider's integration
contract specifies a minimal verification call as model plus messages, and no
released experiment authorizes a local output cap. The gateway timeout remains
`null`, so the upstream ends communication; the workflow does not impose a
separate elapsed-time decision. The request has no inference retry, fallback,
redirect, or policy mutation. An exclusive evidence reservation is flushed before discovery;
the pending marker and directory entry are flushed again before the only POST.
An existing reservation is never reclaimed, including after failure or an
ambiguous timeout. Actions reruns skip the probe even on a fresh runner.

Do not manually dispatch a second run to recover an ambiguous outcome. The local
reservation does not persist across unrelated fresh runners, and artifact upload
can fail after an inference; lack of an artifact is not proof that no request was
sent. Inspect the original run and provider receipts instead. A workflow rerun is
not a billing retry mechanism.

The artifact `experiential-billing-<run_id>` retains only validated provenance,
identities, status, token counts and costs for seven days. It contains no prompt,
completion, credential, raw catalog/account data, exception text, or error body.
Publication must be verified on the hosted run; local tests are not publication
or billing proof.

## Correlation and discovery

The completion's `x-request-id` selects `/api/v1/generation?id=<id>`. The probe
conservatively accepts its cost only when the returned record explicitly echoes
that ID or `gen-<id>`; an omitted ID is not manufactured from the request parameter.
An absent or mismatched echo leaves generation cost and three-way comparison
unknown without discarding independently correlated settled charged credits.
This extra acceptance check is not a claim that the provider guarantees an echo.
A unique persisted `safety_identifier` is sent with the request and must match the settled
row's `attribution_label`. A usage-row ID is not assumed equal to the completion
request ID. Export pagination passes all three documented cursor fields back
until `next_cursor=null`; a malformed or repeated cursor remains unknown. The
provider documents pull/poll but publishes no settlement-ready signal, cadence,
or research-backed stopping policy, so the probe performs one immediate
generation read and one complete settled-export observation. Missing receipts
stay unknown rather than being admitted by an arbitrary polling interval or
round count. No undocumented status enum is used: the documented settled export
is the source, with `pricing_known=true`.

Selection requires an exact authenticated callable ID in the active, text-capable
public catalog and the literal free promotion. The probe preserves that exact
ID. Undocumented `canonical_slug` mappings and provider-prefix stripping are not
used; unresolved identity or multiple eligible promotion identities prevent
inference rather than invoking an undocumented lexical tie-break. Provider model,
promotion, request, and receipt identities are syntax-validated and secret-filtered
without a local length-admission threshold; numeric Actions run identities likewise
have no undocumented digit ceiling. Catalog discovery follows
pagination reported by the provider's first page (`total`, `limit`, `offset`),
requires exact consistent coverage, and does not invent a local page or row
ceiling. Every page must explicitly supply the same `promotions` list; missing,
non-list, or unequal observations fail discovery before any inference POST.
This is a conservative consistency requirement while page-local versus global
promotion semantics remain undocumented, not a claim about provider guarantees.
No missing promotion values are filled or merged. Promotions are metadata
observations, not guarantees about
account eligibility, caps, provider waterfall, or a later request's price.

## Response resource admission

`run_probe(..., response_max_bytes=<operator integer>)` binds the same explicit
budget to each native transport operation; `_request` also refuses a missing
budget. Before credential lookup, evidence creation or any provider send, native
admission requires the operator budget to cover the existing ModelClient error
reader's `MAX_PROVIDER_ERROR_BODY_BYTES + 1` bytes. Smaller budgets are
**unsupported for this native transport**, not silently increased; the value
comes from the shared core error-reader constant, not a provider price or size
heuristic. The common ModelClient reader is unchanged. On HTTP >=400 it can
acquire at most that envelope, then the probe discards the error body entirely:
no partial error JSON becomes a cost/charge claim, and no oversize-error-body
classification is claimed. Injected offline transports own their own acquisition
and are not evidence of native resource admission. `response_max_bytes` is
retained in the artifact.
For successful responses the reader validates every Content-Length declaration,
including repeated fields and comma-joined members, before acquisition; only
identical decimal lengths are accepted. It rejects a declared length beyond
that budget before body acquisition; otherwise it reads at most budget plus one
sentinel byte and rejects excess or truncated declared bodies. HTTP errors are
not parsed for billing evidence; their framing is owned by the unchanged core
reader, not this success-response framing validator. There is no unbounded
adapter fallback. Oversized successful bodies are not parsed or treated as
complete catalogs or zero-price receipts. HTTP status is classified before
consumed HTTPError.close; ordinary cleanup Exception cannot replace it, while
BaseException remains visible. This does not change propagated error ownership
or the separate common response lifecycle owner (#1140).
`response_resource_admission=exceeded` distinguishes unsupported response evidence
from a billing observation. Discovery failure prevents the POST; post-send
refusal remains ambiguous and cannot authorize replay. A separately complete,
exactly correlated settled receipt can still report a charge, but missing receipts
and cost comparison remain unknown. No raw body or exception text is published.

This bounds individual response acquisition and JSON input size, **not total RSS**,
provider-generated tokens, cumulative provider-declared catalog pages, cursor
history, or wall-clock time. The operator must consider JSON object expansion and
full catalog accumulation; this change does not claim a process-wide memory
budget. Provider pagination, null timeout, and single observation remain unchanged.
An admission refusal is never billing truth and must not be recovered by another
inference dispatch. No fixed response ceiling is inferred from provider docs.

The existing `ModelClient._read_bounded_response` was inspected, but its legacy
TypeError compatibility path calls unbounded `read()`, and it does not reject a
short body against the original Content-Length. It is therefore not reused or
changed in this isolated probe fix. Other catalog/search readers use fixed
local caps with different contracts. No streaming JSON parser dependency exists
in this source/lock inventory; no package or invented parser is introduced.

## Local verification and current acceptance

Use the project's existing isolated Python interpreter:

```bash
python -W error -m pytest tests/test_experiential_billing_probe.py \
  tests/test_experiential_review_fixes.py \
  tests/test_experiential_response_budget_successor.py \
  tests/test_provider_bootstrap_secret_normalization.py \
  tests/test_release_checks_required_allowlist.py \
  tests/test_repository_security_metadata.py -q
actionlint .github/workflows/provider-catalog-sync.yml
git diff --check
```

Tests inject offline transport and fixture credentials. They verify one POST,
pre-send persistence, exact callable identity, cost separation, unknown evidence,
pagination, rerun exclusion, bootstrap-to-KV behavior, secret-safe output, and
owned response/error closure. They do not prove complete production transport
connection closure; inherited ModelClient lifecycle ownership remains #1140.

The PR #1350 private successor at `8d9b770c` reproduces three reviewer
failures: shared workflow concurrency, decimal underflow/false agreement, and
unbounded native HTTP acquisition (GET and POST). Focused RED JUnit and logs
remain in the private candidate receipt directory. The successor's focused
strict suite (`test_experiential_billing_probe.py`, reviewer regressions,
bootstrap normalization, release allowlist, repository metadata) passed
**175 tests, 0 skipped** with `-W error`; `actionlint` and `git diff --check`
returned exit 0. These are offline fixtures, not a hosted charge or workflow
execution. Existing historical counts below refer to previous sources.

On 2026-09-30, the inherited implementation baseline was one failed test (missing
`run_probe`) and one passed selector test. The first implementation check passed
26 offline contracts with warnings treated as errors. A later RED contract proved
that two eligible promotions were selected lexically instead of failing closed.
The repaired focused billing, bootstrap, release-allowlist and repository-security
run passed **93 tests** with
warnings treated as errors (process exit 0). The generation-identity follow-up
then reproduced one failure and three passing identity variants before the fix;
the focused suite passed **97 tests** under the same strict warnings setting.
The no-heuristics bounds follow-up reproduced nine independent failures: the
16-token/minimal-body mismatch, the 1,600-row catalog ceiling, the three-page
settled-export ceiling, three five-second receipt rounds, the 30-second transport
timeout, the 15-minute job timeout, the 200-character provider-identifier ceiling,
the 30-digit run-identity ceiling, and the <=2^53 token-evidence ceiling. The
repaired focused file passes **43 tests** and the documented adjacent verification
command passes **104 tests**
with warnings treated as errors. Provider-declared catalog pages and all
unique settled-export cursors now define completeness; receipts are observed
once, and the request uses the null-timeout minimal-body contract.
Those fixtures do not establish a hosted receipt or charge. The repository
workflow-contract test, `compileall`, and `git diff --check` passed; `actionlint`
is unavailable in this isolated environment, so hosted workflow parsing remains
required. The full repository run completed **5,257 passed, 6 skipped, 54 failed,
30 errors** and is not claimed GREEN; the dominant error cluster could not import
the optional `contextual_orchestrator._decision_receipt` native module, while
additional unrelated suites failed. A protected predecessor rerun was not used
as a workaround because the test process could contact an external provider.
An ambiguous send can collect a charge by its persisted attribution label
without replaying inference; send ambiguity is still recorded separately.
Authenticated inference count remains **zero** and measured charge remains **unknown** until the hosted
probe is protected, dispatched once, and its correlated receipts are inspected.

## Sources and reuse

[Official machine-readable API documentation](https://platform.experientiallabs.ai/llms.txt),
retrieved 2026-09-30, documents the API origin, exact callable slugs, request
attribution, generation lookup, settled export, cost distinctions, and cursor
pagination. The public `/api/models` response observed on that date supplies
promotion fields and `total`, `limit`, and `offset`; those fields are validated
rather than treated as undocumented billing guarantees. No full-account usage
export is published.

Reuse the existing credential registry, validated DNS-pinned ModelClient
transport, and atomic canary evidence writer. Standard-library exclusivity and
fsync supply the additional pre-send boundary. No new runtime dependency,
shared transport modification, or billing subsystem is introduced.
