# Provider-neutral reasoning-effort profiles

## Customer next action

Construct `default_role_effort_catalog()` only for an evaluation or an
explicitly configured deployment, run `run_equal_budget_ablation(true_theta)`,
and keep production defaults unchanged while
`production_default_change_allowed(report)` is `false`.

## Contract

`ReasoningEffortProfile` is a versioned, JSON-safe snapshot for thinker,
worker, verifier, synthesizer, planner, and judge. It validates finite numeric
budgets, rejects booleans-as-numbers and unknown keys, and keeps
`reasoning_effort` separate from `temperature`, `top_p`, and `seed`.

The catalog is hashed canonically to identify declared configuration in
synchronous route, streaming route, batch route, generated planning,
verification, and persisted runs. The proposed request-revision repair below
captures the declared effort catalog and effective orchestration policy once
per outer execution. It does not freeze the agent pool. Cached completions
include both the catalog hash and policy content in their key, and persisted
runs preserve the completed result's snapshots
instead of relabeling it with later settings. See the
[cache attribution repair](DISTRIBUTED_RESPONSE_CACHE.md#effort-catalog-attribution-repair-2026-09-06)
for the preceding sequential repair and its historical limits.
A provider must explicitly declare
`reasoning_effort_supported=true` before the native field is sent. Unknown
support fails closed; the explicit `omit` fallback sends only independently
valid output and sampling controls.

The ablation emits estimated `theta_hat`, RMSE against supplied true
parameters, token budget, workflow/depth/access-list factors, and an
`estimated` measurement status. Synthetic estimates are evidence for tests,
not production quality claims, and cannot unlock a default change.

## Request revision contract (Proposed)

### Policy attribution repair (2026-09-06)

An operator can disable judging, obtain a cached answer, enable judging, and
request the same answer again. At `0bf86aca`, that unit reproduction returns
the unjudged cache entry with zero worker/judge calls but saves the new policy
as if it had applied. Bypass runs one worker and one judge. This is a local
reproduction, not evidence of a production incident or measured buyer harm.

Product requirement: enabling answer evaluation must not silently reuse an
answer produced under a different evaluation policy. Requests already running
must retain their starting policy through retries, final synthesis, pending
batch rows, and persistence; later independent requests must see updates.

In the context of operator policy updates during model execution,
facing unjudged answer reuse and incorrectly attributed evaluation records,
we decided for extending the existing request context with the immutable policy
and against cache-only partitioning, per-reader arguments, or a global lock,
to achieve consistent execution and record attribution without serializing requests,
accepting an additive completion field, cold entries for the new key format,
and context-local reads that retain the starting policy until request exit.

Cache-only partitioning leaves in-flight and completion-to-persistence drift.
Threading a new argument through every existing reader duplicates the shared
boundary. A global lock makes unrelated provider waits block one another.
The existing Python adapter owns these lifecycle operations; no estimation
kernel, dependency, provider fallback, or production routing default is added.

The policy property returns the active request's immutable value. Assignment
publishes a configured value for subsequent independent requests. Capture
precedes catalog validation; it is not an atomic multi-setting update API.
The full conducted provider adapter also establishes the scope, so its final
Responses/chat synthesis and saved record use the same policy and effort as
the evidence workflow. Direct single-role passthrough retains its existing
contract and is not forced through six-role validation.

Completion results now include `policy_snapshot`; saved runs copy it, including
detached nested lists. Legacy/test-double completions without this field retain
the prior configured-policy fallback. All changeable policy fields partition
both local and shared caches; equal policy content preserves cache identity.
This does not retroactively verify historical answers. The deterministic
selection receipt's policy hash describes the effective request policy, while
assignment propensity remains `not_identified`.

RED `d70e68488e30aa4bb569dca8d1d2ce03c9ad1ddf` fails **12 cases in 0.26 seconds**.
Source `6d4b5ac70ed62e732fec22f95887414488a14c9b` passes those 12 and the previous
24 effort guards (**36 passed in 0.57 seconds**). At `55d5202a`, **262 focused
tests pass in 14.30 seconds**, including standalone CEFR, provider passthrough,
batch boundaries, streaming, and mixed-pool effort selection. Final test head
`c922329e4f7297a22f83f5f6977af2f8321998f5` passes **48 request/cache guards in
1.10 seconds** and both request test files' default Ruff checks.

The 47-case coverage run at `55d5202a` covers **52/52 statements and 14/14
branches** in nine context/snapshot definitions: the decorator, its two
wrappers, policy getter/setter, scope manager, effort reader, role lookup, and
metadata attachment. The coverage function map collapses the getter/setter
name, so the getter's two statements were additionally checked against the
file-level executed-line set. This is not whole-orchestrator, all-condition,
or exhaustive concurrency coverage. The changed-definition docstring census
against main `414f2297` is **196/196** at `c922329e` (runtime 42, scripts 44,
tests 110), distinguishing property accessors rather than dropping the getter.

The correctness KPI is 12 failing policy-attribution cases to zero. Existing
once-per-request catalog-validation assertions still pass, including a policy
update inside validation. No latency, buyer accuracy, causal identification,
measurement invariance, or released delivery improvement is inferred from
unit correctness or code coverage.

Evidence: `/tmp/co-1067-policy-snapshot.hC9q25`, including `red-pytest.log`,
`green-pytest.log`, `focused-valid-{pytest.log,junit.xml}`,
`final-guard-{pytest.log,junit.xml}`, and `coverage.json`. The first expanded
guard run had five test-only failures from using `policy_hash` instead of the
existing `policy_snapshot_hash`; `guard-pytest.log` preserves them. An initial
focused command named a nonexistent test file and exited 4 with no tests;
`focused-pytest.log` is not a passing run. No runtime contract was renamed to
make those mistakes pass. Reproduce the final guards with:

```sh
.venv/bin/python -m pytest -q tests/test_request_policy_snapshot.py \
  tests/test_request_effort_snapshot.py tests/test_distributed_cache_truth_and_isolation.py
uv tool run --offline ruff check tests/test_request_policy_snapshot.py \
  tests/test_request_effort_snapshot.py
```

Before this policy change, corrected exact clean parent `0bf86aca` completed
**3,494 passed/two skipped in 661.00 seconds** and child `a762e433` completed
**3,509 passed/two skipped in 663.74 seconds**, both exit 0 with matching
start/end heads. Their `corrected-full-*` artifacts remain separate from the
failed effort-scope runs below. They do not verify this later policy repair;
it requires its own frozen full suites, hosted checks, review, and release.

### Requirement and decision

Product requirement: an operator's effort/policy update must affect later independent
requests without changing a request already in progress. The answer, attempted
role profiles, effort component of selection identity, cache identity, and
saved settings must describe the same declared revision. Independent
requests must not wait behind a global lock. Provider compliance with the
declared controls remains a separate observation.

In the context of opt-in effort settings shared by concurrent requests,
facing mixed execution and record revisions after operator updates,
we decided for one validated request-local catalog snapshot
and against constructor-wide freezing, a global execution lock, or metadata-only relabeling,
to achieve consistent attribution while allowing independent requests to progress,
accepting context-management overhead and a separate agent-pool consistency boundary.

This is the implementation proposal for [ADR 0021](../planning/adrs/0021-reasoning-effort-profiles.md),
not a newly accepted ADR or release. Constructor-wide freezing would hide
legitimate later updates. A lock would serialize provider waits and would not
control mutations of the caller-owned mapping. Relabeling output alone would
leave mixed profiles in workflow steps and retries.

### Technical contract and sequence

`complete`, direct `route_once`/`conduct`, `batch_route`, `stream_route`, and
the conducted provider-completion adapter
establish the boundary. Same-instance nested routing reuses it; a different
orchestrator has its own revision and restores the caller's context on return.
An entire `batch_route` invocation shares one revision. A stream captures it
at first iteration, before selection, preserving normal generator laziness.
At those boundaries, malformed catalog roles/values fail before provider execution, including
cache-disabled and explicit bypass paths. A request started without a catalog
retains that absence even if an operator opts in before it finishes.

Standalone single-role adapters remain outside that full-workflow boundary.
For example, the existing CEFR Responses adapter can configure only a judge
profile. Its role lookup preserves that established contract, including when
another orchestrator owns the surrounding request context. Missing roles
remain absent; starting a full workflow with that partial catalog still fails
before execution. This distinction does not promise a request-wide snapshot
for the standalone adapter.

The existing canonical snapshot and immutable policy are held in a module-level
`ContextVar` with their owning instance. Policy, profile, key, and evidence
readers reuse them. The
mutable role mapping is copied before validation, and exported metadata is
deep-copied so one returned batch row cannot change another. Stream advancement
and close run in a copied context; yielding restores the caller's context, so
interleaved streams do not borrow one another's effort settings. Exceptions
and early close release the active context. No dependency, statistical kernel,
global lock, new provider call, or production routing default is introduced.

```mermaid
sequenceDiagram
    participant Caller
    participant Request as Request context
    participant Catalog as Operator settings
    participant Worker as Execution
    participant Record as Saved evidence
    Caller->>Request: Start execution or first stream iteration
    Request->>Catalog: Capture policy P; copy and validate catalog S
    Request->>Worker: Execute roles, retries, and final synthesis with P and S
    Catalog->>Catalog: Operator publishes later settings Q and T
    opt Streaming
        Worker-->>Request: Content delta
        Request-->>Caller: Yield with caller context restored
    end
    Worker-->>Request: Completed result
    Request->>Record: Save result with detached P and S metadata
    Request-->>Caller: Return and release context
    Caller->>Request: Start later independent request
    Request->>Catalog: Capture Q; copy and validate T
```

The existing Python control-plane adapter owns this context boundary; it adds
no numerical estimation implementation. Rust-first statistical ownership is
unchanged. The diagram does not promise an atomic transaction over deployment
metadata, the mutable agent pool, sampling overrides outside the role catalog,
or independent operator updates of multiple settings. Same-instance nested
calls belong to their outer execution scope; the catalog is not a general
per-call override API.

### Exact local evidence and KPI

RED `beae9fb45f13d9401357444f0d527ba4be64645a` fails all eight reproduction
cases in 0.34 seconds. Source `1eff633810e0269afda349ae8ccacba3bc9e447d`
passes them in 0.37 seconds. At guard head
`1edf574b81a7d25c9eb54d47a10afd063375c1a6`, **317 integration tests pass in
18.90 seconds**. The focused request suite contains **23 passing cases**,
including actual overlapping threads, interleaved streams, early close,
provider errors, retry, nested orchestrators, malformed catalogs, default-path
opt-in, cache replay, detached batch rows, and later-request updates.
Test-only lint cleanup `ec3ad654` passes the same 23 cases in 0.42 seconds and
the environment's default Ruff selection for the new test file.

The 23-case coverage run at `1edf574b` covers all **43 statements and 12
branches** across the scope decorator and its two wrappers, scope context
manager, snapshot reader, profile reader, and metadata attachment. All seven
definitions are documented. This is not whole-orchestrator or exhaustive
concurrency-interleaving coverage. The changed-definition census against main
`414f2297` is **173/173**: runtime 37/37, scripts 44/44, tests 92/92, using the
existing AST-difference scope rather than excluding private/nested definitions.

The first full runs exposed a compatibility regression omitted by that focused
set: parent `f660d71f` finished with **one failure, 3,492 passed, two skipped in
658.68 seconds**, and child `44a49529` with **the same failure, 3,507 passed,
two skipped in 668.91 seconds**. Both frozen clean heads matched at start/end,
and both exited 1. The existing CEFR judge-only Responses test was rejected by
full-catalog validation inside the shared standalone profile lookup. These
runs remain failures, not flaky results or evidence of full acceptance.

RED `0a5e24b78cd2c9ef9593b075d0810309143ddef0` adds the direct single-role and
foreign-context regression; it and the unchanged CEFR test fail in 0.51 seconds.
Source `e4314c18ecc7a2b1c4894a6439ff4f134abd1596` restores the old standalone
lookup while retaining validated snapshots inside owned full-request scopes.
Changing the CEFR fixture to add unused roles or weakening full-request
validation was rejected because either would hide the contract mismatch.
On this clean correction, **118 request/CEFR/judge/client-boundary tests pass
in 1.52 seconds**, and the 24-case request coverage run passes in 0.45 seconds.
The same seven definitions cover **47/47 statements and 14/14 branches**;
the changed-definition census is **174/174** (runtime 37, scripts 44, tests 93),
and the new test file passes default Ruff. Corrected full-suite and hosted
acceptance need their own evidence. The historical operation-count comparison
below retains its original revisions.

For a fixed one-worker unit fixture with real-time judging disabled and cache
disabled, the number of real catalog validations per completion changes as
follows. The baseline is `beae9fb4`, the candidate is `1edf574b`; answer,
snapshot, and selected deployment identities are equal between versions.

| Mode | Catalog | Before | After |
|---|---|---:|---:|
| Route | Opted out | 0 | 0 |
| Conduct | Opted out | 0 | 0 |
| Route | Opted in | 2 | 1 |
| Conduct | Opted in | 5 | 1 |

This is an operation-count KPI with zero external calls, **not a wall-clock
latency result**, quality improvement, or buyer p95 result. The correctness KPI
is eight failing revision fixtures to zero, with the broader guards retained.

Reproduce the request guards and validation-count invariant:

```sh
.venv/bin/pytest -q tests/test_request_effort_snapshot.py
.venv/bin/python -m coverage run --branch -m pytest -q tests/test_request_effort_snapshot.py
.venv/bin/python -m coverage json -o request-effort-coverage.json
uv tool run --offline ruff check tests/test_request_effort_snapshot.py
```

Evidence is in `/tmp/co-1067-request-effort.3j8tar`: `red-pytest.log`,
`green-{pytest.log,junit.xml}`, `final-focused-{pytest.log,junit.xml}`,
`final-coverage-{pytest.log,data}`, `final-coverage.json`, and
`validation-count-profile.json`. Full-suite, hosted checks, independent review,
protected merge, immutable release, and live provider/measurement validity
remain separate gates. Synthetic unit fixtures cannot authorize production.
The failed full run is preserved as `full-{pytest.log,junit.xml}` in each
request-effort evidence directory; the child directory is
`/tmp/co-1074-request-effort.tMoMjv`. Correction evidence is
`compatibility-{pytest.log,junit.xml}` and `compatibility-coverage.json` in the
parent directory. Do not overwrite failed full-run artifacts with later runs.

## Verification

```text
uv run pytest -q tests/test_reasoning_effort_profile.py tests/fuzz/test_fuzz_properties.py
uv run ruff check .
```

## Research basis (APA 7th)

Python Software Foundation. (n.d.). *contextvars — Context variables*.
Python documentation. Retrieved September 6, 2026, from
https://docs.python.org/3/library/contextvars.html

Sakana AI. (2026). *Sakana Fugu technical report*.
https://github.com/SakanaAI/fugu/blob/main/Fugu_technical_report.pdf

Xu, J., Sun, Q., Schwendeman, P., Nielsen, S., Cetin, E., & Tang, Y. (2025).
*Trinity: An evolved LLM coordinator* (arXiv:2512.04695).
https://doi.org/10.48550/arXiv.2512.04695

Nielsen, S., Cetin, E., Schwendeman, P., Sun, Q., Xu, J., & Tang, Y. (2025).
*Learning to orchestrate agents in natural language with the Conductor*
(arXiv:2512.04388). https://doi.org/10.48550/arXiv.2512.04388

Baker, F. B. (2001). *The basics of item response theory* (2nd ed.). ERIC
Clearinghouse on Assessment and Evaluation. https://eric.ed.gov/?id=ED458219
