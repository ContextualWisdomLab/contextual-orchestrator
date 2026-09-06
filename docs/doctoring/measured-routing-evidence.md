---
title: "Measured routing evidence: latency ledgers, semantic affinity, triage, real-time judging"
status: "proposed; local implementation evidence, protected delivery unverified"
date: "2026-08-25"
scope: "PR (stacked on #834), ADR 0034"
---

# Measured routing evidence

## Decision

ADR 0034 removes every task-keyword heuristic from the routing path and
replaces it with an evidence ladder: operator-declared eligibility, exact
tag/priority/cosine ordering, and measured member behavior inside model
groups. Two measurement systems feed the ladder:

- **Transport ledger** — Beta(1,1)-posterior success stability divided by
  EWMA latency, using Jacobson's (1988) 1/8 gain and a floor at
  `MIN_ROUTING_LATENCY_SECONDS` so division never amplifies noise.
- **Quality ledger** — the same Beta-Bernoulli arithmetic fed by the
  real-time fast-mlsirm judge on direct-route answers, so judged
  acceptability (not just transport success) steers intra-group order.

The ranking quantity `stability / ewma_latency_seconds` is a model-based
successful-responses-per-second score, not an independently calibrated rate.
Its validity depends on the prior, observation process, and latency denominator.
Token throughput remains
diagnostic evidence and is not mixed into that score. Workflow triage is a strict structured call that
fails closed to conducted orchestration when its reply violates the exact
`{"workflow_required": bool}` schema.

## Research-to-code mapping

### Availability and answer-quality separation (2026-09-06)

**Proposed implementation repair, not protected delivery.** The product
requirement is that a provider availability update cannot rewrite evidence
about whether an answer was acceptable. A reachable endpoint may return an
incorrect answer. Applying AERA, APA, and NCME (2014, pp. 11–12, Standard 1.2)
to this gateway is an engineering interpretation: the evidence supporting an
intended score interpretation must match that interpretation. Those standards
do not themselves validate this gateway or its judge.

OpenRouter's endpoint API reports `uptime_last_30m` separately from latency
and throughput. It does not report answer correctness. The existing collector
reads the maximum reported endpoint uptime; that maximum is not the observed
success rate of the gateway's actual provider mix. See the official
[endpoint API](https://openrouter.ai/docs/api/api-reference/endpoints/list-all-endpoints-for-a-model).
The API documents authorization, while this collector's fetch currently sends
none. This repair uses injected measurements and makes **zero external provider
calls**; it establishes neither successful live polling nor a production incident.

#### Failure, decision, and alternatives

The old collector accumulated availability windows and refreshed **both**
transport and quality priors. `ModelGroupRouter.update_prior` preserved the
observed success/failure counters but changed the quality posterior and its
response to later real judgments. The production selection path
`_ranked_agents` → `_refine_partition` → `_measured_member_order` uses the
quality ledger once judged observations exist. Counter preservation alone
therefore did not protect answer-quality ordering.

In the context of evidence-based member selection, facing unrelated uptime
changing answer-quality evidence, we chose a transport-only collector
dependency and rejected shared quality-prior updates or a new combined score,
to preserve the meaning of judged outcomes, accepting that transport-prior
calibration remains unresolved. This enforces ADR 0034's existing separation;
it introduces no new statistical core, dependency, weight, or migration.

Source `b3be48e31138877b6f99fe7288beef8528c46828` removes the collector's
quality-router argument and reference, deletes its two-router wrapper, and
updates the existing gateway wiring. Transport refresh uses the existing
neutral prior constants plus the unchanged window mass, without importing an
answer-benchmark prior. The ledgers are process-local. Repository constructor
callers are updated; direct users of the internal collector must remove the
old quality-router argument. The collector is not a package-root export.

```text
Provider availability summary -> transport prior -> fallback member order
Answer judgment -------------> quality ledger ---> judged member order
                              no uptime input
```

#### Runnable guards and measured KPI

The fixed unit scenario contains two equivalent declared members, with 8/10
and 2/10 accepted answers and successful-answer latency fixed at one second.
Each member then receives 50 availability-only polls: 0% for the stronger
judged member and 100% for the weaker one. There are no additional judgments.

| Boundary KPI | Baseline collector | Repaired collector |
| --- | --- | --- |
| Quality posterior means before polls | 0.75 / 0.25 | 0.75 / 0.25 |
| Quality posterior means after polls | 0.145161 / 0.854839 | 0.75 / 0.25 |
| Maximum absolute reported-mean drift | 0.604839 | 0 |
| Actual measured-group order | Reversed | Preserved |

The controlled probe swaps collector source `450599f1` against `e5775648`
inside the same current gateway; it is not a replay of two complete deployed
builds. `paired-boundary-probe.json` in `/tmp/co-1067-uptime-quality.OI92QL`
retains both complete quality snapshots and exact source identities.

Committed RED `450599f15e84d7dc505d61b01f027f8270c54da0` produces **8 failures,
7 passes in 1.31 seconds**, exit 1. Six cases combine cold/judged members with
0%, 50%, and 100% uptime. They compare both the immediate snapshot and the
effect of a subsequent real judgment: 50% uptime can hide added prior mass
behind an unchanged mean. The other guards cover actual selection order and
independence from a substituted answer-benchmark resolver. The latter uses a
valid member ID; it does not establish that canonical member IDs match the
benchmark table's hyphenated names.

The earlier RED attempt `5d1f7e35` had six failures and nine passes, including
one invalid hyphenated member-ID fixture. Its log is retained, but that setup
failure is not counted as a product regression. At source `b3be48e3`, **100
focused tests pass in 5.01 seconds**. Coverage from 15 passing tests is scoped
to the collector constructor and `_poll_agent`: **19/19 statements, 4/4
branches**; fetch, the entire gateway constructor, and the whole repository
are not covered by that claim. Clean style head
`e5775648223d561bacba93022a06c720f9d5613c` passes **132 focused tests in 234.74
seconds**, exit 0. Changed-definition docstrings against main `414f2297` are
**205/205** (runtime 45, scripts 44, tests 116), not a whole-repository census.

```sh
.venv/bin/python -m pytest -q tests/test_openrouter_uptime.py \
  tests/test_model_group.py tests/test_measured_routing_evidence.py \
  tests/test_benchmark_priors.py tests/test_request_policy_snapshot.py \
  tests/test_psychometric_routing.py
```

Logs, JUnit, and coverage JSON are retained in the probe directory above.
Full-suite and hosted evidence must name their own exact heads; earlier
policy-snapshot full runs do not verify this later repair.

#### Limits and next acceptance gates

The invariant is zero quality change under availability-only input, not
true-parameter RMSE, calibrated correctness, buyer accuracy, or reduced
decision latency. It does not refute IRT-Router. Overlapping 30-minute windows
remain correlated transport pseudo-counts; their accumulation and endpoint
maximum need separate validation. The existing median/MAD–logistic benchmark
prior and substring identity mapping also remain uncalibrated, separate gaps.
Any replacement numerical model belongs to the canonical released Rust owner,
not a Python clone. No production default or psychometric admission gate is
opened. Independent review, terminal required checks, protected merge,
immutable release, and observed buyer-held-out evidence remain necessary.

### Endpoint percentage input validation (2026-09-06)

**Proposed input-boundary repair.** Availability evidence must come from a
numeric percentage in the inclusive range 0–100. The existing fetch converted
booleans and strings with `float`, selected the endpoint maximum, and clamped
the result. Consequently, malformed input could add apparently valid window
mass without a valid measurement. This is separate from the interpretation
and calibration of valid rolling windows.

RFC 8259 Section 6 excludes NaN and Infinity tokens; Python's default JSON
decoder nevertheless accepts them as extensions. A grammatically valid large
exponent can also exceed the receiver's numeric range. Successful parsing is
therefore insufficient. The official OpenRouter endpoint example reports
numeric uptime separately from latency and throughput; neither source
justifies coercing a boolean/string into a percentage.

In the context of upstream telemetry admission, facing invalid values changing
routing evidence, we chose validation before endpoint aggregation and rejected
clamping/coercion or silently selecting another endpoint, to prevent invented
window mass, accepting that a mixed valid/invalid payload contributes no update.
Null and missing values retain their existing absent-measurement behavior;
they are not transport failures. Source `b49d583fcdb0f13fd98cde76dfcb187229f52d6f`
reuses the fetch boundary and its existing no-update error path. No new
dependency, statistical estimator, authentication behavior, or routing weight
is introduced. Both modified methods and both added tests have docstrings.

```text
Endpoint response -> numeric type and [0, 100] validation -> endpoint maximum
                 -> invalid value: no update             -> transport window
                 -> null/missing: absent                    (not answer quality)
```

Committed RED `e405b803b4ca888680c66218ea9e5a5d2d3ff848` produces **33 failed,
28 passed in 0.47 seconds**, exit 1. Of 39 invalid-payload cases, six existing
object/array cases already reject input; 33 incorrectly update evidence.
The cases cover NaN, signed infinities, exponent overflow, booleans, numeric
strings, out-of-range values, and placement before/after a valid endpoint.
Seven additional payload controls retain valid boundaries, fractional values,
endpoint maximum, null/missing values, and empty lists. All exercise actual
fetch-to-poll parsing with an in-memory HTTP response, including response
closure and unchanged observed-outcome counts; external provider calls are zero.

At source `b49d583f`, **98 collector/group/prior tests pass in 1.83 seconds**,
exit 0. The invalid-payload ledger-mutation KPI improves **33/39 to 0/39**
in these unit cases, not in an observed production population. A separate
61-test coverage run passes in 0.90 seconds and covers the two changed methods
at **27/27 statements and 8/8 branches**; it does not prove exhaustive parser,
whole-module, transport-provider, or buyer coverage. Default Ruff passes.

```sh
.venv/bin/python -m pytest -q tests/test_openrouter_uptime.py \
  tests/test_model_group.py tests/test_benchmark_priors.py
```

Logs, JUnit, and coverage JSON are in `/tmp/co-uptime-input.rjxaB9`. The preceding
provider-wait full suites are terminal: parent `7b634397` has 3,520 passes/two
skips in 778.16 seconds; child `2f770351` has 3,535 passes/two skips in 771.71
seconds, both exit 0 with matching clean heads. They predate this input repair.
Current-head full/hosted checks, independent review, protected delivery, and
new-head Visual Inspection remain separate requirements. Earlier desktop
screenshots do not verify these new revisions; the last browser attempt was
blocked by the locked Mac. Calibration, live collection, buyer accuracy, and
decision latency are not established by this input-validation result.

### Full-suite follow-up: provider completion contract (2026-09-06)

Full-suite follow-up to the availability repair: clean parent `6ca30364`
completed **3,520 passed/two skipped/exit 0 in 1,624.03 seconds**. Child
`0707e524` completed **one failed/3,534 passed/two skipped/exit 1 in 1,723.01
seconds**. Matching clean start/end heads and JUnit are retained in the two
`/tmp/co-1067-uptime-quality.OI92QL` and
`/tmp/co-1074-uptime-quality.ji78pd` directories. Neither session is still live.

The failure was a test contract error, not demonstrated availability-source
breakage: `test_unknown_tokenizer_uses_authoritative_provider_usage` expected
immediate completion from an asynchronous provider backend without supplying
the existing explicit `wait_timeout`. Barrier-controlled RED `cfef8462`
reproduces the same running-versus-completed failure deterministically in
6.38 seconds. Test repair `8d1ea613` supplies that wait in the two affected
tests (including three Unicode cases) and closes their resources. **137
provider/batch/cost/registry tests pass in 16.64 seconds**, exit 0. Runtime
asynchrony, provider-failure behavior, budget gates, exact token assertions,
and production timeout policy are unchanged. This does not excuse the failed
full run; corrected exact-head full runs must use separate artifacts.

### Evaluation-policy attribution (2026-09-06)

An evaluation outcome must be attributed to the policy that actually produced
it before comparing routing regimes or attempting psychometric estimation.
The [policy-attribution repair](reasoning-effort-profile.md#policy-attribution-repair-2026-09-06)
connects a twelve-case unit failure baseline to source `6d4b5ac7`: cached answers,
in-flight judging, selection receipts, and saved runs retain the same effective
policy. The 12 cases pass after repair; `55d5202a` passes 262 focused integration
tests, and `c922329e` passes 48 final request/cache guards.

This establishes a local software attribution invariant, not measurement
invariance or construct validity. Deterministic receipts still do not identify
assignment probabilities or unobserved outcomes. No inverse-propensity weights,
new estimator, buyer accuracy gain, production default, or causal claim is
introduced. Exact evidence and the remaining delivery gates are in the linked
Proposed record; the statistical-core/release owner boundary is unchanged.

### Complete changed-definition audit (2026-09-06)

At `d740602f`, comparison with protected main `414f2297` found **90/129**
documented changed definitions: runtime 24/26, scripts 44/44, tests 22/59.
Documentation-only `02f60c40e0d1d9f8b0fe79ca8d8c53b43cda0903` adds the 39
missing docstrings and reaches **129/129**, including classes, initializers,
private methods, and nested test helpers. The seven modified Python files have
identical docstring-stripped ASTs to `d740602f`. Ruff passes, and **235 focused
tests passed in 20.57 seconds**, terminal exit 0 on the unchanged clean commit.

The scope includes definitions whose AST differs from the declared base,
including differences in docstrings and nested bodies. Unchanged definitions,
module docstrings, non-Python files, and the rest of the repository are outside
this count. It is not CodeRabbit's historical 107-function scope or a behavioral
coverage result. The full-size numerical assertions, fixture populations,
provider exclusions, persisted-run visibility, and production gates are
unchanged. Offline live-mode doubles remain explicitly separate from live
provider evidence.

Reproduce the exact count and executable-structure guard with the existing
project Python and Git, without installing an audit package:

```sh
.venv/bin/python - <<'PY'
import ast
import collections
import json
import subprocess

base_revision = "414f22973658c4ddc3d4320fcf7acd9b4e8ba991"
original_revision = "d740602fdd8c0e4f7d55e4d3ad37b9f560c09e01"
head_revision = "02f60c40e0d1d9f8b0fe79ca8d8c53b43cda0903"
def git_source(revision, file_name):
    result = subprocess.run(["git", "show", f"{revision}:{file_name}"], capture_output=True, text=True)
    return result.stdout if result.returncode == 0 else ""
def definitions(source):
    found = {}
    def visit(node, parents=()):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                qualified_name = (*parents, child.name)
                found[".".join(qualified_name)] = child
                visit(child, qualified_name)
            else:
                visit(child, parents)
    visit(ast.parse(source))
    return found
def stripped_ast(source):
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and ast.get_docstring(node) is not None:
            node.body = node.body[1:]
    return ast.dump(tree, include_attributes=False)
file_names = subprocess.check_output(["git", "diff", "--name-only", base_revision, head_revision, "--", "*.py"], text=True).splitlines()
summary = collections.defaultdict(lambda: {"changed_definitions": 0, "documented": 0, "missing": []})
for file_name in file_names:
    old_defs = definitions(git_source(base_revision, file_name))
    for qualified_name, node in definitions(git_source(head_revision, file_name)).items():
        old_node = old_defs.get(qualified_name)
        if old_node is not None and ast.dump(node, include_attributes=False) == ast.dump(old_node, include_attributes=False):
            continue
        scope = "tests" if file_name.startswith("tests/") else "scripts" if file_name.startswith("scripts/") else "runtime"
        record = summary[scope]
        record["changed_definitions"] += 1
        if ast.get_docstring(node):
            record["documented"] += 1
        else:
            record["missing"].append(f"{file_name}:{node.lineno}:{qualified_name}")
changed_files = subprocess.check_output(["git", "diff", "--name-only", original_revision, head_revision, "--", "*.py"], text=True).splitlines()
unequal = [file_name for file_name in changed_files if stripped_ast(git_source(original_revision, file_name)) != stripped_ast(git_source(head_revision, file_name))]
print(json.dumps({"base": base_revision, "head": head_revision, "summary": dict(summary), "docstring_stripped_ast_comparison": {"original": original_revision, "files": changed_files, "unequal": unequal}}, indent=2))
assert not unequal, unequal
assert sum(row["changed_definitions"] for row in summary.values()) == 129
assert all(not row["missing"] for row in summary.values()), dict(summary)
PY
```

Focused verification:

```sh
.venv/bin/pytest -q tests/test_endpoint_race.py tests/test_nim_benchmark.py \
  tests/test_provider_reliability.py tests/test_psychometric_benchmark_boundaries.py \
  tests/test_psychometric_routing.py tests/test_true_streaming.py \
  tests/test_agent_pool_db.py tests/test_docstring_coverage.py \
  tests/test_product_planning_contract.py
```

The evidence directory is `/tmp/co-1067-changed-docs.VmQM1v`:
`ast-audit.json` and `focused-valid-{pytest.log,junit.xml}`. An initial command
named nonexistent `tests/test_paper_inventory.py` and exited 4 without running
tests; its separately retained log is not source-failure or passing evidence.
The actual paper contract is `tests/test_paper_contracts.py`.


### Operation-local identity snapshot (2026-09-06)

The performance review exposed repeated catalog validation in ranking and
decision records. RED `ad3fbf87` also demonstrates mixed catalog versions when
an attempt iterable changes caller-owned settings between record fields.
Source `db195d73` materializes each input batch, validates one catalog snapshot,
and preserves every candidate occurrence. Existing canonical JSON and SHA-256
identity semantics remain unchanged for fixed settings. Subsequent calls take
fresh snapshots; malformed catalog updates still fail closed. This does not
claim an atomic transaction across the agent pool, policy, catalog, and an
entire long-running provider request.

Persistent object-identity caching was rejected because the catalog and nested
deployment contract are mutable. The existing Python orchestration adapter
reduces repeated validation; it adds no statistical kernel or Rust replacement.
The Rust-first numerical-owner boundary and all buyer admission gates remain.

At guard-test head `2d1592af`, 206 integration tests pass, and seven cases cover
all 16 statements/four branches of the three identity/record methods. The
[reproducible profile](../research/psychometric-identity-batch-profile.json)
contains all cross-process and within-process samples, including the earlier
default-path regression and first calls. Same-process alternation controls
process differences; it does not identify the cause of the earlier regression.
The opt-in 50-candidate fixture's pooled median is 9.121 versus 0.677417 ms across
189 calls per version. Default medians (0.481667 versus 0.478208 ms) do not justify
a speedup claim. All outputs match within each condition. These are controlled
unit-fixture costs, not buyer observations or end-to-end performance evidence.

### Internal benchmark contract audit (2026-09-05)

The documentation audit covers the psychometric routing module and both
psychometric benchmark scripts, including their private and nested functions.
Use an empty configuration to avoid importing repository exclusions:

```sh
.venv/bin/interrogate -c /dev/null --fail-under 100 \
  contextual_orchestrator/psychometric_routing.py \
  scripts/benchmark_psychometric_routing.py \
  scripts/benchmark_psychometric_heldout.py
.venv/bin/pytest -q tests/test_psychometric_routing.py \
  tests/test_psychometric_benchmark_boundaries.py \
  tests/test_benchmark_priors.py tests/test_docstring_coverage.py
```

At `ae704491`, 41 of 61 entities had docstrings. Documentation-only `f8b142aa`
raises this to 61/61 and leaves the docstring-stripped ASTs unchanged; its
48-test run passed in 24.99 seconds. Subsequent `1710cfe7` removes one existing
unused assignment reported by F841, passes Ruff and the same strict docstring
check, and passes the 48 tests in 18.24 seconds. No other executable AST change
remains after accounting for that exact assignment.

The new contracts explicitly identify oracle fit-cache injection, synthetic
true-probability calibration, selected-item-order response draws, unresolved
candidate costs, and conditional classification risk. A Wilson endpoint used
in a seeded screen is not an anytime-valid sequential guarantee. Pooled local
ranking p95 and paired context medians do not measure end-to-end model latency.
These distinctions document existing calculations without changing an estimator,
sample size, production policy, or the wider CodeRabbit documentation scope.

Subsequent normal merge `2340bea5` retains #1064 head `4c4e5f13` and its
protected-main cost-evidence update; 244 integration tests passed in 32.90
seconds. A later protected-main transport-retry correction (`414f2297`) is
preserved by merge `c4008bb5`, whose 157 transport, failover, psychometric-routing,
and streaming tests passed in 23.56 seconds. Logs and JUnit are retained in
`/tmp/co-1067-documentation-audit.h2ZVMV`. These are distinct exact-head local
checks, not a measured end-to-end latency gain or protected delivery claim.

### IRT-Router interpretation audit (2026-09-05)

This review separates the ACL 2025 paper from public implementation revision
`e8f258ced4ec3c40d795403603acd8c1cdfb994d`. AERA, APA, and NCME (2014, p. 11)
require support for each intended score interpretation; prediction and ability
measurement are distinct claims. Multidimensional or explanatory IRT is not
rejected merely for using multiple abilities or covariates.

| Evidence | Supported reading | Unmet interpretation requirement |
| --- | --- | --- |
| Paper §3.2 connects monotonicity with interpretability. | A directional response constraint is an interpretable modeling choice. | Validate the named construct, measurement unit, and intended use separately. |
| Paper Eq. (4) prints a linear discrimination transform; public MIRT code lines 51–59 add softplus or a range-scaled sigmoid. | The default implementation has positive discrimination; a configured range must also be positive. | Do not describe the implementation as unconstrained, or infer invariant scales from a positive direction. |
| Figure 4 compares the mean of 25 fitted ability coordinates. | The figure describes one fitted representation. | Identify the coordinate units and justify aggregation before calling that mean comparable general ability. |
| §4.2.2 and Appendix C assign ability labels using five sampled questions per cluster and GPT-4o Mini. | The labels are a proposed content mapping. | Validate that mapping and its coverage before interpreting a named dimension as measured ability. |

An algebraic counterexample clarifies the aggregation issue. In the printed
Eq. (5), the logit is `aᵀθ - b`. For any positive diagonal matrix `C`, replacing
`θ` with `Cθ` and `a` with `C⁻¹a` leaves that logit unchanged for every pair.
For two illustrative ability vectors `(2, 0)` and `(0, 1)`, their averages are
`1` and `0.5`. Rescaling by `C = diag(0.1, 10)` changes the averages to `0.1`
and `5`, reversing their order without changing predictions when discrimination
is transformed inversely. Positive discrimination stays positive.
This is a hand-checkable mathematical example, not empirical LLM data,
checkpoint manipulation, or a proof that every neural parameter constraint
admits the same transformation. The constrained implementation still needs its
own identification analysis; an arbitrary coordinate average is not justified
by predictive loss alone.

The gateway consequently treats IRT-Router as a response-prediction reference,
not a certificate of stable ability. Missing validation is not a demonstrated
assumption violation. Buyer evidence must separately establish construct and
item-content coverage, identification and linking, fit and residual dependence,
appropriate candidate-group or item-side invariance, and estimation uncertainty.

The existing default-change input helper was also audited. RED `76908a55`
reproduced ten invalid approvals and two unhandled numeric-overflow cases.
Source `0ad54cdf` reuses the existing finite-number validator, requires explicit
`measured` status, rejects negative candidate RMSE and nonpositive baseline RMSE,
and retains the 55% improvement requirement and valid zero candidate error.
The 52-test profile suite passed with 100% statement and branch coverage.
This helper checks declarations only: it neither authenticates observation
provenance nor changes production defaults. Its `True` result cannot replace
buyer measurement validation, independent review, or protected release approval.
The separate held-out routing harness continues to require all its own gates.

### Existing implementation evidence

| Implementation boundary | Evidence-informed reason | Acceptance evidence |
| --- | --- | --- |
| EWMA with gain 1/8 for latency and throughput | Jacobson's congestion-avoidance estimator is the canonical low-pass filter for volatile network measurements; it needs no tuning window. | Exact-arithmetic tests reproduce hand-computed EWMA values. |
| Laplace rule of succession as stability prior | Beta(1,1) is an explicit uniform-prior assumption, not a uniquely assumption-free estimate (Gelman et al., 2013). | Stability tests assert alpha/(alpha+beta) exactly; arithmetic does not validate that prior for buyer outcomes. |
| Cosine similarity over declared metadata documents | Karpukhin et al. (2020, Section 3.1) use learned dense representations and dot-product similarity. CO's normalized cosine over operator-declared descriptors is a separate adaptation, not their validated routing method. | Deterministic mock-embedding tests verify cosine ordering and zero-vector guards. |
| Strict JSON triage verdict | Zheng et al. (2023) study judge agreement and position, verbosity, self-enhancement, and reasoning limitations. The exact JSON contract is CO's fail-closed parsing decision; syntactic validity cannot establish judgment accuracy. | Parser tests reject seven malformed-reply classes and cache verdicts by content hash; buyer judge calibration remains separate. |
| Probability calibration | Cox (1958) motivates logistic recalibration; Arrieta-Ibarra et al. (2022) distinguish calibration diagnostics from aggregate probabilistic scores. | Source `92b9309b` moves held-out calibration slope from `0.991445` to `1.014030` and reduces logit RMSE from `0.231235` to `0.025803`; the paired improvement interval is `[-0.208030, -0.202924]`. Synthetic truth does not replace buyer outcome calibration. |
| Real-time judging before returning answers | RouteLLM/FrugalGPT motivate quality-aware routing between models (Ong et al., 2024; Chen et al., 2023); here quality is measured per deployment instead of trained offline. | Judge-driven failover tests prove rejection routes to the next candidate within budget while updating both ledgers. |
| Candidate-specific evidence and interactions | Jeon et al. (2021) model item–respondent interactions in a latent metric space. Separate per-member ledgers do not implement that model or by themselves prevent cross-level inference errors; buyer hierarchy, dependence, and generalization need separate evidence. | Quality-ledger reports expose per-member posteriors; their existence does not establish a multilevel measurement model. |
| Language/domain validity boundary | IRT-Router treats LLMs as persons and queries as items, so query language cannot be inserted as a person-group DIF label. A released explanatory-IRT covariate supports one item-side difficulty contrast (Debeer & Janssen, 2013); Multilingual-IRT additionally separates language from content discrimination (Lior et al., 2026). | Source `0f875e3f` converges after 941 iterations and estimates `-0.789650` for a known `-0.8` contrast. The synthetic report still keeps `measurement_validity=false`; preregistered covariates, anchors, and linked buyer observations remain required, while language-specific discrimination and residual effects remain unavailable. |
| Parameter uncertainty boundary | Oakes (1999) derives observed information for EM fits; Pritikin (2017) compares covariance estimators for item-factor models. | Source `b0f3703f` reuses the released Oakes API: six known intercepts have RMSE `0.039160`, 95% interval coverage `1.0`, and mean width `0.295945`. Buyer calibration remains required, and the current API conditions on population parameters and rejects anchors, zero inflation, and item covariates. |
| Recalibration invariance boundary | Millsap (2010) requires longitudinal invariance before changes in the latent construct are interpreted; Babcock and Albano (2012) show common-item drift can damage linked classifications. | Source `2e129e2a` links through seven stable anchors and flags the one injected drift item with no stable-item false positive. The fixed `0.25` tolerance is an effect-size screen only; buyer recalibrations, sampling uncertainty, and review rules remain required. |
| Candidate-roster invariance boundary | Tinsley and Dawis (1975) connect sample-free calibration to adequate sampling, unbiased design, and model fit. | Source `5c6ba17a` separately fits 20- and 16-candidate synthetic rosters and links 200 common items. Linked common-score RMSE is `0.010866`, correlation is `0.999999`, and maximum shift is `0.016498`; versioned buyer rosters and registered shift targets remain required. |
| Functional drift impact | Guo, Zheng, and Chang (2015) evaluate drift by its effect on the test characteristic curve rather than isolated parameter distance. | Source `c7c4a13f` detects the one injected function-changing item and reduces TCC-area difference from `0.123355` to zero. The released backward-only fixed-threshold heuristic is not the paper's full stepwise method; buyer recalibrations and preregistered review rules remain required. |
| Sequential drift delay | Chen, Lee, and Li (2022) frame item drift monitoring as sequential change detection with compound false- and missed-detection risk. | Source `1b3b7244` searches 11 thresholds on 500 calibration runs using a 95% Wilson false-alarm bound, then evaluates threshold `6.6` on an independent 500-run seed. Held-out false alarms are `2.4%` with upper bound `4.15%`; delay p50 is 10 and p95 is 20 observations. Buyer time series, risk weights, and preregistered targets remain required. |
| Alternate-form score equating | AERA, APA, and NCME (2014, Standards 5.16–5.18) require evidence for comparable score meaning across alternate item sets; Moses and Holland (2008) provide an observed-score equating framework with uncertainty. | Source `1dce9688` recovers known slope `2` and intercept `1`, reducing raw cross-form RMSE from `6.782330` to zero. Three hundred bootstrap 95% intervals cover all 11 known equivalent scores; buyer forms, comparable populations or anchors, and error targets remain required. |
| Candidate response-pattern fit | Meijer (1996) and Tendeiro et al. (2016) treat person fit as a screen for response vectors that depart from a model or comparison group. With LLM deployments in the person role, this becomes a candidate-pattern review signal. | Source `a18e25f7` ranks one injected inverted pattern first among 1,000 candidates, with ZU3 separation `1.818719` from the next-highest pattern. It does not infer a cause or apply a universal cutoff; complete buyer candidate-by-criterion responses and a review policy remain required. |
| Construct dimensionality screen | Horn (1965) compares observed roots with random-data roots; Tran and Formann (2009) show that parallel analysis, especially with Pearson correlations, is unreliable as proof of unidimensionality for binary items. | Source `73e07a8e` recovers the two known dimensions in a seeded 1,000-response, 12-item simulation. This is an implementation screen only; buyer responses, a preregistered construct structure, and confirmatory holdout fit remain required. |
| Global model-fit screen | Maydeu-Olivares and Joe (2005) derive limited-information goodness-of-fit tests for binary contingency tables; Xu et al. (2017) show that M2 sensitivity depends on the multidimensional structure. | Source `7f13dc7d` accepts a fitted one-factor synthetic case at `p=0.105619` and detects known two-factor misspecification at `p≈2.27e-41`. Complete buyer responses, a preregistered model, and held-out fit review remain required. |
| Score reliability | Bechger et al. (2003) connect IRT posterior uncertainty with classical reliability; Stanley and Edwards (2016) show that reliability and model fit answer different questions. | Source `5b50e10c` raises empirical reliability from `0.366437` to `0.800436` when known discrimination rises from `0.45` to `1.5`. Buyer calibration, posterior errors, a purpose-specific target, and separate fit evidence remain required. |
| Cross-condition generalizability | Huebner and Lucht (2019) separate person, item, occasion, and interaction variance and use D-studies to evaluate alternate evidence designs. | Source `015c4bf6` decomposes an 80-candidate, 12-query, four-occasion synthetic tensor. Dependability rises from `0.401565` at one query and one occasion to `0.849616` at 12 and four; complete balanced buyer observations, random-facet justification, and a registered target remain required. |
| Conditional information | Lord (1950) requires precision to be evaluated at the ability level where a decision is made; Magis (2013) grounds the item-information calculation. | Source `b4efa489` improves worst information across trait points `[-2, 0, 2]` by `15.789%` when 12 item difficulties cover `[-2, 2]`, reducing worst conditional standard error from `0.890897` to `0.827931`. Buyer-relevant regions and calibrated buyer items remain required. |
| Classification decision error | Rudner (2001, 2005) evaluates classification accuracy and consistency from the score-error distribution around an explicit cut. | Source `0b19116e` reduces synthetic standard error from `0.8` to `0.2`, raising expected accuracy from `0.814182` to `0.996895` and consistency from `0.710275` to `0.993829`. Buyer cuts, linked measures, decision costs, and preregistered targets remain required. |
| Decision utility boundary | Taylor and Russell (1939) connect validity, selection ratio, and base rate to expected selection outcomes; the Brogden-Cronbach-Gleser model subtracts measurement cost from valued outcome gain. | Source `452a3649` raises synthetic validity from `0.2` to `0.6`, increasing selected success from `0.500273` to `0.723515` and net utility from `2,042.21` to `5,626.64`; holding validity fixed while raising total cost to `10,000` changes net utility to `-2,373.36`. This personnel-selection model is an analogue, not validated routing economics; buyer outcome units, costs, volume, and targets remain required. |
| Predictive-fit axes | Stenhaug and Domingue (2022) distinguish missing-response prediction for observed persons from complete-response prediction for new persons. | Source `68831dff` labels the existing synthetic held-out-query Brier and log-loss evidence as the known-candidate task. Source `54833bd8` executes the unseen-candidate path across 24 contexts and measures zero psychometric prediction coverage. Versioned buyer outcomes for both axes remain required. |
| Adaptive candidate onboarding | Bock and Mislevy (1982) ground adaptive EAP scoring; Hau and Chang (2001) evaluate maximum-information selection at early CAT stages. | Source `f4513527` reuses the released Rust-backed path across 400 known synthetic candidates. Maximum-information selection reaches SE 0.5 in 7.1775 queries on average versus 10.47 for random order. Paired 95% intervals are `[-3.4125, -3.18]` queries, `[-0.080874, 0.006129]` theta squared error, and `[-0.008804, -0.005716]` unobserved-probability squared error. The theta interval includes zero. It measures calibration-query burden, not live decision latency, buyer validity, or invariant ability. |
| Classification-oriented stopping and rejection | Luo, Kim, and Dickison (2018) describe CI stopping; Chow (1970) and El-Yaniv and Wiener (2010) frame abstention as an error–coverage tradeoff; Morris, White, and Crowther (2019) require Monte Carlo uncertainty for simulated performance. | Source `e1ff2e61` chooses `z=1.645` on a development seed. Source `609faff8` rejects it after only 20% of ten independent runs satisfy the declared error ceiling. Source `1862893a` reports that pass-rate estimate's MCSE as 0.1265 and requires 400 worst-case replications for a 0.025 MCSE; coverage-delta, query-delta, and risk MCSEs are 0.00619, 0.02257, and 0.00211. Ten seeds expose instability but do not precisely estimate its operating characteristics. Buyer fallback policy, adequately powered preregistration, calibrated intervals, and live latency remain unexecuted. |
| Decision-time implementation cost | The accuracy experiment must also beat the existing one-neighbor route-decision wall time without changing fitted scores or cosine semantics. | Source `0b87905c` replaces a Python generator with `map(operator.mul, ...)` inside the existing `math.fsum`. Across ten before/after process runs, candidate p50 median falls from 0.01325 to 0.007708 ms (41.83%) and the latency-delta CI-upper median falls from 0.000910 to 0.000635 ms (30.14%). The delta remains positive, so the latency gate still fails; this is local CPU timing, not end-to-end provider latency. |
| Positive-propensity logging design | Horvitz and Thompson (1952) establish unequal-probability weighting; Dudík et al. (2011) and Swaminathan and Joachims (2015) apply logged propensities to partial-feedback policy evaluation while warning about variance. | A fixed-seed ε-greedy simulation gives every candidate probability at least 0.05: the ranked winner receives 0.85 and each other candidate 0.05. It observes every candidate, reports inverse-propensity value RMSE 0.008943, and covers all four known true values with its 95% intervals. Buyer validity remains unexecuted. |

## Accuracy and decision-latency KPI

Run
`uv run --python 3.12 python scripts/benchmark_psychometric_routing.py`.
Python 3.12 is explicit because the locked NumPy/fast-mlsirm benchmark
dependencies are intentionally unavailable on the product's supported Python
3.10 and 3.11 runtimes. The benchmark
fixes the native fit and probability output, then measures only gateway matrix
preparation and ranking for 512 contexts, four models, and two dichotomous
items per context. Lower median milliseconds is better; the psychometric and
reasoning-effort tests must remain green.

Protected `main@2e414d15` measured 2.448167 ms. Candidate performance commit
`0561c9b81f68bd9be9bd413f4a23892717e54701`, carried by PR #1058, measured 1.100583 ms, a
55.04% reduction. This local same-host result does not prove production
latency or answer accuracy. The next accuracy experiment must use a held-out
model-query matrix and report log loss or Brier score alongside routing regret;
true-parameter simulations must continue to report RMSE.

The successor observation-path experiment uses the same 512-context ledger.
Replacing one model/context row fell from p50 0.133833 ms and p95 0.152166 ms
on `b2f90116` to p50 0.000875 ms and p95 0.001000 ms. The benchmark now emits
both fields. This is local gateway bookkeeping evidence; the fit, held-out
quality, and provider latency remain separate KPIs.

Run `uv run --python 3.12 python scripts/benchmark_psychometric_heldout.py` for the separate,
explicitly enabled semantic warm-start experiment. Production retains the
validated single-neighbor behavior. On its fixed 24-training/24-held-out smooth
latent-response surface, the single-neighbor baseline at `0ae0ed8c` reports
Brier 0.1438369123, log loss 0.4525311878, mean top-choice regret 0.0024259478,
and decision p50 about 0.0212 ms. Two-neighbor positive-cosine interpolation at
`50d91c9e`, carried by PR #1061, reports Brier 0.1418346845, log loss
0.4475784303, zero top-choice regret, and p50 near 0.02 ms. Source commit
`94615dff` adds paired, seeded 2,000-resample bootstrap intervals and 200 timing
repetitions per held-out context, alternating execution order to reduce warmup
and drift bias. A same-host run reports candidate-minus-baseline Brier `[-0.0022969, -0.0016986]`,
log loss `[-0.0053736, -0.0045191]`, and regret `[-0.0072778, 0]`; candidate
p50 was 0.0386 ms versus baseline 0.0340 ms, with paired context-median latency
delta `[0.0047666, 0.0054775]` ms. This seeded simulation isolates
unseen-context interpolation; it is not a substitute for preregistered buyer
prompts, observed judge outcomes, or end-to-end latency. The experimental result
cannot alter live routing while the latency and buyer-validity gates remain open.
Report-contract commit `2cc8427f` emits each candidate-minus-baseline point
delta beside its interval and tests that the metric sets match and every point
lies inside its reported interval.
Fail-closed gate commit `079b3f80` separately reports accuracy non-inferiority,
decision-latency improvement, buyer-heldout status, and measurement validity.
This synthetic run passes only accuracy; therefore
`production_default_change_allowed` is false.
Production-path source commit `70cfc91f` restores one-pass `max()` selection for
the single-neighbor default while retaining full top-2 ordering only inside the
experiment. A same-process 512-row `timeit` comparison measured 5.5 µs for
`max()` versus 27 µs for `sorted(..., reverse=True)[:1]`; this isolates neighbor
selection and is not an end-to-end route-latency claim.
Experimental source commit `972bd4a0` reads the two selected score maps once
per candidate rather than rebuilding filtered numerator and denominator
generators. Ten whole-process pairs alternated baseline/candidate order. The
median candidate decision p50 fell from `0.0180415` to `0.016708` ms (7.39%);
the paired context-median latency-delta CI upper bound fell from `0.0022899` to
`0.0006677` ms (70.84%). Brier `0.1418346845`, log loss `0.4475784303`, and
regret `0` were identical in every pair. Because the CI upper bound remains
positive, this improvement does not open the latency or production gate.
Source commit `260fa1dd` then computes the validated query-vector norm once per
decision rather than once for every retained context. Across five before/after
local runs, median candidate p50 fell from `0.023167` to `0.015042` ms (35.07%)
and the median paired latency-delta CI upper bound fell from `0.0008368` to
`0.0006112` ms. Brier, log loss, and regret remained bit-identical. The latency
and production gates remain closed because the interval upper bound is positive.
Source commit `1309b3ce` separates observed failure from absent evidence:
accuracy is `passed`, latency is `failed`, and buyer-heldout plus
measurement-validity gates are `not_executed`. The legacy Boolean view derives
strictly from `status == "passed"`, preserving fail-closed compatibility.
Source commit `c690ebe7` makes the measurement-validity denominator explicit:
scale linking, local independence, correctly oriented candidate-group DIF,
item-side language/domain effects, judge effects, and adaptive exposure must
each carry evidence. All six currently report `not_executed`.
Source commit `fdb8e57a` also separates released owner contracts from the
pending local-independence contract and contracts then classified as
unimplemented. It records the buyer evidence each check still needs without
treating API availability as completed validation; later evidence corrects the
two overly broad classifications below.
Source commit `7edccae0` caches the validated unit vector for each retained
context at observation time. Across five before/after local runs, median
candidate p50 fell from `0.016083` to `0.009791` ms (39.12%) while Brier, log
loss, and regret remained identical. The candidate-minus-baseline latency CI
upper bound remained positive, so the production latency gate stays closed.
Source commit `00b2eef3` corrects the item-side owner status from
`not_implemented` to `released_limited`. The installed `fast-mlsirm` 0.9.1
contract can estimate one multigroup item covariate coefficient; it cannot
claim the richer language-specific discrimination or residual model.
Source commit `a095b41f` similarly separates released CAT exposure control
from the missing gateway observation-design contract. `fast-mlsirm` 0.9.1 can
calibrate an exposure filter, but it cannot reconstruct routing propensities or
unobserved candidate outcomes that CO never recorded.
Source commit `46e15555` adds a secret-free selection-design receipt to route,
conducted-workflow, and streaming trace rows. It binds the ordered candidate
deployments, actual attempts, selected deployment, and policy snapshot while
labeling the current deterministic assignment propensity `not_identified`.
This supplies an auditable observation denominator; it does not identify
counterfactual outcomes or open the adaptive-exposure gate.
Source commit `2c783b98` preregisters a benchmark-only ε-greedy logging policy
with 20% exploration across four candidates and 24,000 fixed-seed trials. Every
candidate receives probability at least 0.05; Horvitz-Thompson estimates reach
RMSE 0.008943 against known synthetic truth and all four 95% intervals cover
their targets. Source `36dbf3bb` adds the missing naive comparison: treating
adaptively selected observations as ignorable yields RMSE `0.321979`, so logged
inverse-propensity estimation reduces error by `0.313036`. This validates
executable propensity arithmetic, not buyer
outcomes, and does not change production selection.
Source commit `ca6e9a75` validates the released common-item linking contract.
Six anchors undergo a known `slope=1.3`, `intercept=-0.4` metric change;
Stocking–Lord linking converges and recovers both coefficients with
true-parameter RMSE `3.24e-16`. These exact synthetic anchors prove the
calculation path, not cross-version buyer invariance, so `scale_linking`
remains `not_executed` for production.
Source commit `d0d81e8f` validates candidate-cohort DIF screening with a
known shifted item. The unpurified screen also flags an invariant item because
the matching total is contaminated; iterative logistic purification stabilizes
with seven anchors, detects the one injected item (recall 1.0), and has zero
false positives. The result is synthetic contract evidence, so buyer DIF stays
`not_executed`.
Source commit `ac28b6d0` validates judge-severity recovery with a connected,
fully crossed 1,000-respondent × 6-item × 3-judge design. The many-facet Rasch
fit converges in five iterations, preserves severity order, and reports RMSE
0.018292 against centered true severities `[-0.7, 0, 0.7]`. Versioned buyer
judges and observed buyer ratings remain absent, so `judge_effects` stays
`not_executed`.

## Review correction evidence (2026-09-05)

The review of source `6d1b30803888e893d7bdbdf4d12605a16c36162d`
found literal subgroup denominators tied to 400 candidates. RED commit
`43706aad` reproduces coverage above 100% at 401 and 403 candidates.
Source `a8109a65` derives all three subgroup sizes from the same generated
trait grid used by the experiment and subtracts directional rates rather than
counts. Empty or unresolved summaries fail explicitly; they are never reported
as zero error. Default candidate counts, response seeds, repetitions, and
admission gates are unchanged. These are harness corrections, not new
estimators or evidence of buyer accuracy.

The full suite using executable source `a8109a65` finished with 3,432 passing
tests, two skips, and exit 0 in 728.31 seconds, including the existing
full-size experiment assertions. Documentation edits were checked separately
with 102 passing routing, paper, and boundary tests. Hosted acceptance and
buyer calibration remain unverified.

The same source keeps nearest-rank observation p95 dependent on the actual
sample count (101 by default) and shares the Python 3.12 startup guard before
optional numerical imports. The race-reentry regression confirms that a
deployment called again after race failure must occur again in the selection
receipt. The receipt records selection attempts, not a unique deployment set
or a complete transport/tool-retry ledger; its multiplicity cannot be discarded
or used alone to certify all provider costs or an exposure probability.

The research table now separates source findings from CO-specific choices:
Beta(1,1) remains an assumption; DPR's dot product is not this gateway's cosine
policy; a JSON parser does not validate a judge; and per-member ledgers do not
prove a multilevel model. The ADR diagram separates the production
single-neighbor default from opt-in two-neighbor held-out experiments.

## APA 7 references

Bray, T. (Ed.). (2017). *The JavaScript Object Notation (JSON) data interchange
format* (RFC 8259). Internet Engineering Task Force.
https://www.rfc-editor.org/rfc/rfc8259

Python Software Foundation. (n.d.). *json: JSON encoder and decoder*.
https://docs.python.org/3/library/json.html#infinite-and-nan-number-values

OpenRouter. (n.d.). *List all endpoints for a model*. Retrieved September 6,
2026, from https://openrouter.ai/docs/api/api-reference/endpoints/list-all-endpoints-for-a-model

American Educational Research Association, American Psychological
Association, & National Council on Measurement in Education. (2014).
*Standards for educational and psychological testing*. American Educational
Research Association. https://www.testingstandards.net/open-access-files.html

Arrieta-Ibarra, I., Gujral, P., Tannen, J., Tygert, M., & Xu, C. (2022).
Metrics of calibration for probabilistic predictions. *Journal of Machine
Learning Research, 23*(351), 1–54.
https://www.jmlr.org/papers/v23/22-0658.html

Babcock, B., & Albano, A. D. (2012). Rasch scale stability in the presence of
item parameter and trait drift. *Applied Psychological Measurement, 36*(7),
565–580. https://doi.org/10.1177/0146621612455090

Barrada, J. R., Olea, J., & Ponsoda, V. (2007). Methods for restricting maximum
exposure rate in computerized adaptive testing. *Methodology, 3*(1), 14–23.
https://doi.org/10.1027/1614-2241.3.1.14

Bechger, T. M., Maris, G., Verstralen, H. H. F. M., & Béguin, A. A. (2003).
Using classical test theory in combination with item response theory.
*Applied Psychological Measurement, 27*(5), 319–334.
https://doi.org/10.1177/0146621603257518

Bock, R. D., & Aitkin, M. (1981). Marginal maximum likelihood estimation of
item parameters: Application of an EM algorithm. *Psychometrika, 46*(4),
443–459. https://doi.org/10.1007/BF02293801

Bock, R. D., & Mislevy, R. J. (1982). Adaptive EAP estimation of ability in
a microcomputer environment. *Applied Psychological Measurement, 6*(4),
431–444. https://doi.org/10.1177/014662168200600405

Brogden, H. E. (1949). When testing pays off. *Personnel Psychology, 2*(2),
171–183. https://doi.org/10.1111/j.1744-6570.1949.tb01397.x

Chen, L., Zaharia, M., & Zou, J. (2023). *FrugalGPT: How to use large
language models while reducing cost and improving performance*. arXiv.
https://arxiv.org/abs/2305.05176

Chen, W.-H., & Thissen, D. (1997). Local dependence indexes for item pairs
using item response theory. *Journal of Educational and Behavioral Statistics,
22*(3), 265–289. https://doi.org/10.3102/10769986022003265

Chen, Y., Lee, Y.-H., & Li, X. (2022). Item pool quality control in
educational testing: Change point model, compound risk, and sequential
detection. *Journal of Educational and Behavioral Statistics, 47*(3),
322–352. https://doi.org/10.3102/10769986211059085

Chow, C. K. (1970). On optimum recognition error and reject tradeoff. *IEEE
Transactions on Information Theory, 16*(1), 41–46.
https://doi.org/10.1109/TIT.1970.1054406

Cox, D. R. (1958). Two further applications of a model for binary regression.
*Biometrika, 45*(3–4), 562–565.
https://doi.org/10.1093/biomet/45.3-4.562

Debeer, D., & Janssen, R. (2013). Modeling item-position effects within an IRT
framework. *Journal of Educational Measurement, 50*(2), 164–185.
https://doi.org/10.1111/jedm.12009

Doebler, A. (2012). The problem of bias in person parameter estimation in
adaptive testing. *Applied Psychological Measurement, 36*(4), 255–270.
https://doi.org/10.1177/0146621612443304

Dudík, M., Langford, J., & Li, L. (2011). Doubly robust policy evaluation and
learning. In *Proceedings of the 28th International Conference on Machine
Learning* (pp. 1097–1104). https://arxiv.org/abs/1103.4601

Eckes, T. (2015). *Introduction to many-facet Rasch measurement* (2nd ed.).
Peter Lang. https://doi.org/10.3726/978-3-653-04844-5

El-Yaniv, R., & Wiener, Y. (2010). On the foundations of noise-free selective
classification. *Journal of Machine Learning Research, 11*, 1605–1641.
https://www.jmlr.org/papers/v11/el-yaniv10a.html

Finkelman, M., Nering, M. L., & Roussos, L. A. (2009). A conditional exposure
control method for multidimensional adaptive testing. *Journal of Educational
Measurement, 46*(1), 84–103.
https://doi.org/10.1111/j.1745-3984.2009.01070.x

French, B. F., & Maller, S. J. (2007). Iterative purification and effect size
use with logistic regression for differential item functioning detection.
*Educational and Psychological Measurement, 67*(3), 373–393.
https://doi.org/10.1177/0013164406294781

Gelman, A., Carlin, J. B., Stern, H. S., Dunson, D. B., Vehtari, A., &
Rubin, D. B. (2013). *Bayesian data analysis* (3rd ed.). CRC Press.

Guo, R., Zheng, Y., & Chang, H.-H. (2015). A stepwise test characteristic
curve method to detect item parameter drift. *Journal of Educational
Measurement, 52*(3), 280–300. https://doi.org/10.1111/jedm.12077

Hau, K.-T., & Chang, H.-H. (2001). Item selection in computerized adaptive
testing: Should more discriminating items be used first? *Journal of
Educational Measurement, 38*(3), 249–266.
https://doi.org/10.1111/j.1745-3984.2001.tb01126.x

He, Y., & Qi, Y. (2023). Using response time in multidimensional computerized
adaptive testing. *Journal of Educational Measurement, 60*(4), 697–738.
https://doi.org/10.1111/jedm.12373

Horn, J. L. (1965). A rationale and test for the number of factors in factor
analysis. *Psychometrika, 30*(2), 179–185.
https://doi.org/10.1007/BF02289447

Horvitz, D. G., & Thompson, D. J. (1952). A generalization of sampling without
replacement from a finite universe. *Journal of the American Statistical
Association, 47*(260), 663–685.
https://doi.org/10.1080/01621459.1952.10483446

Huebner, A., & Lucht, M. (2019). Generalizability theory in R. *Practical
Assessment, Research, and Evaluation, 24*, Article 5.
https://openpublishing.library.umass.edu/pare/article/id/1593/

Jacobson, V. (1988). Congestion avoidance and control. *ACM SIGCOMM
Computer Communication Review, 18*(4), 314–329.
https://doi.org/10.1145/52325.52356

Jeon, M., Jin, I. H., Schweinberger, M., & Baugh, S. (2021). Mapping
unobserved item–respondent interactions: A latent space item response model
with interaction map. *Psychometrika, 86*(2), 378–403.
https://doi.org/10.1007/s11336-021-09762-5

Karpukhin, V., Oguz, B., Min, S., Lewis, P., Wu, L., Edunov, S., Chen, D.,
& Yih, W.-t. (2020). Dense passage retrieval for open-domain question
answering. In *Proceedings of the 2020 Conference on Empirical Methods in
Natural Language Processing* (pp. 6769–6781). Association for
Computational Linguistics. https://doi.org/10.18653/v1/2020.emnlp-main.550

Laplace, P.-S. (1774). Mémoire sur la probabilité des causes par les
événements. *Mémoires de l'Académie Royale des Sciences de Paris, 6*,
621–656. (Rule of succession; modern treatment in Gelman et al., 2013.)

Linacre, J. M. (1989). *Many-facet Rasch measurement*. MESA Press.

Lior, G., Frostig, T., Stanovsky, G., & Eyal, M. (2026). *Extending item
response theory for efficient and meaningful multilingual evaluation*
[Preprint]. arXiv. https://doi.org/10.48550/arXiv.2606.15643

Lord, F. M. (1950). *Properties of test scores expressed as functions of the
item parameters* (Research Bulletin RB-50-56). Educational Testing Service.
https://doi.org/10.1002/j.2333-8504.1950.tb00919.x

Luo, X., Kim, D., & Dickison, P. (2018). Projection-based stopping rules for
computerized adaptive testing in licensure testing. *Applied Psychological
Measurement, 42*(4), 275–290.
https://doi.org/10.1177/0146621617726790

Magis, D. (2013). A note on the item information function of the
four-parameter logistic model. *Applied Psychological Measurement, 37*(4),
304–315. https://doi.org/10.1177/0146621613475471

Maydeu-Olivares, A., & Joe, H. (2005). Limited- and full-information
estimation and goodness-of-fit testing in 2ⁿ contingency tables: A unified
framework. *Journal of the American Statistical Association, 100*(471),
1009–1020. https://doi.org/10.1198/016214504000002069

Meijer, R. R. (1996). Person-fit research: An introduction. *Applied
Measurement in Education, 9*(1), 3–8.
https://doi.org/10.1207/s15324818ame0901_2

Millsap, R. E. (2010). Testing measurement invariance using item response
theory in longitudinal data: An introduction. *Child Development
Perspectives, 4*(1), 5–9.
https://doi.org/10.1111/j.1750-8606.2009.00109.x

Morris, T. P., White, I. R., & Crowther, M. J. (2019). Using simulation
studies to evaluate statistical methods. *Statistics in Medicine, 38*(11),
2074–2102. https://doi.org/10.1002/sim.8086

Moses, T. P., & Holland, P. W. (2008). *Notes on a general framework for
observed score equating* (Research Report No. RR-08-59). Educational Testing
Service. https://doi.org/10.1002/j.2333-8504.2008.tb02145.x

Nadaraya, E. A. (1964). On estimating regression. *Theory of Probability &
Its Applications, 9*(1), 141–142. https://doi.org/10.1137/1109020

Oakes, D. (1999). Direct calculation of the information matrix via the EM.
*Journal of the Royal Statistical Society: Series B, 61*(2), 479–482.
https://doi.org/10.1111/1467-9868.00188

Ong, I., Almahairi, A., Wu, V., Chiang, W.-L., Wu, T., Gonzalez, J. E.,
Kadous, M. W., & Stoica, I. (2024). *RouteLLM: Learning to route LLMs
with preference data*. arXiv. https://arxiv.org/abs/2406.18665

Pritikin, J. N. (2017). A comparison of parameter covariance estimation
methods for item response models in an expectation-maximization framework.
*Cogent Psychology, 4*(1), 1279435.
https://doi.org/10.1080/23311908.2017.1279435

Rudner, L. M. (2001). Computing the expected proportions of misclassified
examinees. *Practical Assessment, Research & Evaluation, 7*(14), 1–5.
https://doi.org/10.7275/an9m-2035

Rudner, L. M. (2005). Expected classification accuracy. *Practical
Assessment, Research & Evaluation, 10*(13), 1–4.
https://doi.org/10.7275/56a5-6b14

Song, W., Huang, Z., Cheng, C., Gao, W., Xu, B., Zhao, G., Wang, F., & Wu, R.
(2025). IRT-Router: Effective and interpretable multi-LLM routing via item
response theory. In *Proceedings of the 63rd Annual Meeting of the Association
for Computational Linguistics (Volume 1: Long Papers)* (pp. 15629–15644).
Association for Computational Linguistics. https://doi.org/10.18653/v1/2025.acl-long.761

Stanley, L. M., & Edwards, M. C. (2016). Reliability and model fit.
*Educational and Psychological Measurement, 76*(6), 976–985.
https://doi.org/10.1177/0013164416638900

Stenhaug, B. A., & Domingue, B. W. (2022). Predictive fit metrics for item
response models. *Applied Psychological Measurement, 46*(2), 128–143.
https://doi.org/10.1177/01466216211066603

Stocking, M. L., & Lord, F. M. (1983). Developing a common metric in item
response theory. *Applied Psychological Measurement, 7*(2), 201–210.
https://doi.org/10.1177/014662168300700208

Swaminathan, A., & Joachims, T. (2015). Batch learning from logged bandit
feedback through counterfactual risk minimization. *Journal of Machine Learning
Research, 16*(52), 1731–1755.
https://jmlr.org/papers/v16/swaminathan15a.html

Swaminathan, H., & Rogers, H. J. (1990). Detecting differential item
functioning using logistic regression procedures. *Journal of Educational
Measurement, 27*(4), 361–370.
https://doi.org/10.1111/j.1745-3984.1990.tb00754.x

Taylor, H. C., & Russell, J. T. (1939). The relationship of validity
coefficients to the practical effectiveness of tests in selection:
Discussion and tables. *Journal of Applied Psychology, 23*(5), 565–578.
https://doi.org/10.1037/h0057079

Tendeiro, J. N., Meijer, R. R., & Niessen, A. S. M. (2016). PerFit: An R
package for person-fit analysis in IRT. *Journal of Statistical Software,
74*(5), 1–27. https://doi.org/10.18637/jss.v074.i05

Tinsley, H. E. A., & Dawis, R. V. (1975). An investigation of the Rasch
simple logistic model: Sample free item and test calibration. *Educational
and Psychological Measurement, 35*(2), 325–336.
https://doi.org/10.1177/001316447503500211

Tran, U. S., & Formann, A. K. (2009). Performance of parallel analysis in
retrieving unidimensionality in the presence of binary data. *Educational
and Psychological Measurement, 69*(1), 50–61.
https://doi.org/10.1177/0013164408318761

Xu, J., Paek, I., & Xia, Y. (2017). Investigating the behaviors of M2 and
RMSEA2 in fitting a unidimensional model to multidimensional data. *Applied
Psychological Measurement, 41*(8), 632–644.
https://doi.org/10.1177/0146621617710464

Zheng, L., Chiang, W.-L., Sheng, Y., Zhuang, S., Wu, Z., Zhuang, Y., Lin,
Z., Li, Z., Li, D., Xing, E., Zhang, H., Gonzalez, J. E., & Stoica, I.
(2023). *Judging LLM-as-a-judge with MT-Bench and Chatbot Arena*. arXiv.
https://arxiv.org/abs/2306.05685
