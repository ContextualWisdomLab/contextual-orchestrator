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

Missing, malformed, negative, nonfinite, unpriced, duplicated, uncorrelated, or
incompletely paginated evidence stays unknown. Explicit zero is accepted only from
one priced, exactly attributed settled row. A mismatch is reported, not averaged
away. One zero-charge sample does not prove future free requests or authorize
production admission.

## Safe execution

Merge through the existing protected reviews first. On protected `main`, manually
dispatch **Provider catalog sync** with `measure_experiential_billing=true`. The
input defaults to false. The probe job is independent of catalog-sync success,
requires the production environment, and runs only on the first Actions attempt.
Scheduled runs and PR code cannot run it. Runtime credentials come from the KV;
the organization secret `EXPERIENTAL_LABS_API_KEY` is environment transport only
for in-process bootstrap. No credential extraction is needed or permitted.

The request uses a fixed synthetic prompt, at most 16 output tokens, and a
30-second transport timeout. It has no inference retry, fallback, redirect, or
policy mutation. An exclusive evidence reservation is flushed before discovery;
the pending marker and directory entry are flushed again before the only POST.
An existing reservation is never reclaimed, including after failure or an
ambiguous timeout. Actions reruns skip the probe even on a fresh runner.

Do not manually dispatch a second run to recover an ambiguous outcome. The local
reservation does not persist across unrelated fresh runners, and artifact upload
can fail after an inference; lack of an artifact is not proof that no request was
sent. Inspect the original run and provider receipts instead. A workflow rerun is
not a billing retry mechanism.

The artifact `experiential-billing-<run_id>` retains only bounded provenance,
identities, status, token counts and costs for seven days. It contains no prompt,
completion, credential, raw catalog/account data, exception text, or error body.
Publication must be verified on the hosted run; local tests are not publication
or billing proof.

## Correlation and discovery

The completion's `x-request-id` selects `/api/v1/generation?id=<id>`. A unique
persisted `safety_identifier` is sent with the request and must match the settled
row's `attribution_label`. A usage-row ID is not assumed equal to the completion
request ID. Export pagination passes all three documented cursor fields back;
more than three pages or a repeated cursor remains unknown. At most three
GET-only receipt polling rounds are performed. No undocumented status enum is
used: the documented settled export is the source, with `pricing_known=true`.

Selection requires an exact authenticated callable ID in the active, text-capable
public catalog and the literal free promotion. The probe preserves that exact
ID. Undocumented `canonical_slug` mappings and provider-prefix stripping are not
used; unresolved identity prevents inference. Catalog discovery follows bounded
`limit=100`/`offset` pages, requires complete consistent coverage, and refuses more
than 1,600 rows. Promotions are metadata observations, not guarantees about
account eligibility, caps, provider waterfall, or a later request's price.

## Local verification and current acceptance

Use the project's existing isolated Python interpreter:

```bash
python -W error -m pytest tests/test_experiential_billing_probe.py \
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

On 2026-09-30, the inherited implementation baseline was one failed test (missing
`run_probe`) and one passed selector test. The first implementation check passed
26 offline contracts with warnings treated as errors. The final focused billing,
bootstrap, release-allowlist and repository-security run passed **92 tests** with
warnings treated as errors (process exit 0). Actionlint and `git diff --check`
also passed. A timeout can collect a charge by its persisted attribution label
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
