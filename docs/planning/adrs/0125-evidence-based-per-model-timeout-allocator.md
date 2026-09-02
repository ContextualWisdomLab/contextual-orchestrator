# ADR 0125: Evidence-Based Per-Model LLM Timeout Allocator

- Status: Proposed
- Date: 2026-09-02
- Responds to: `contextual-orchestrator#1010` (closed by the repository owner
  2026-09-02T05:10:46Z; UI/persistence explicitly left reusable "behind" this
  ADR — see Context)
- Governs alongside: `contextual-orchestrator#971` (open; makes
  `ModelClient.timeout` default to no fixed wall-clock bound at the library
  level)
- Related: ADR 0021 (reasoning-effort profiles), ADR 0033 (admin console
  boundary), ADR 0034 (anti-heuristic routing evidence), `ContextualWisdomLab/.github`
  `docs/adr/0003-contextual-orchestrator-vendored-free-zdr.md` (2026-08-31
  amendment: no fixed wall-clock model-inference timeout for the review
  sidecar)

## Context

`contextual-orchestrator#1010` added an admin-editable per-model timeout
override with `MIN_MODEL_TIMEOUT_SECONDS = 1.0` /
`MAX_MODEL_TIMEOUT_SECONDS = 14400.0`. The repository owner closed it same-day
with a first-person, evidence-based comment: the `1`/`14400` bound was "picked
by analogy, not research," and the PR's own ADR 0042 justified `14400` by
citing `ContextualWisdomLab/.github`'s `NOEMA_LLM_TIMEOUT_SECONDS` constant as
an "already-evidenced" org precedent. That citation does not hold up: fresh
`git log -S`/`git show` against `.github` confirms `NOEMA_LLM_TIMEOUT_SECONDS
= 4 * 60 * 60` was introduced in commit `9b57e4b` (2026-09-01 12:07 KST) with
no measured latency or percentile cited anywhere in that commit — a literal
`4 * 60 * 60` — and was deleted roughly three hours later in commit `5686de4`
(2026-09-01 15:01 KST), the same day, in favor of the ADR-0003 amendment
quoted below. `.github`'s own next commit repudiated the constant PR #1010
cited as evidence *before* PR #1010 was even opened. The owner's closing
comment names the actual condition for reuse: "If a research-/standard-backed
timeout allocator with executable provenance is later implemented, the
UI/persistence work can be selectively reused behind that owner rather than
reviving the 1/14400 rule." This ADR is that allocator's design.

### The org's own standing policy is "no fixed timeout," not "pick a bigger one"

`.github`'s `docs/adr/0003-contextual-orchestrator-vendored-free-zdr.md`
(2026-08-31 amendment, governing the OpenCode/Noema/Strix review sidecar)
states plainly: "model inference has no repository- or
application-configured fixed wall-clock timeout... A slow reasoning model
such as DeepSeek is not unavailable merely because it takes minutes or hours
to produce tokens." `contextual-orchestrator#971` (open, unmerged at time of
writing) extends the same principle to the orchestrator library itself:
`ModelClient.timeout` moves toward no default, and its own PR body states the
"no-inference-timeout contract is universal... It does not inspect model
names, provider names, `reasoning_effort_supported`, or a hand-maintained
reasoning-model list." Any allocator design that outputs a mandatory,
identity-inspecting enforcement path would contradict a policy this org has
now stated twice, independently, in two repositories, within the same week.
This ADR does not do that: it computes an optional, admin-surfaced *suggested*
number — never an enforced default, never an automatic per-model-class branch
in the request path.

### What latency data actually exists today (verified against a fresh clone,
main `8839081`)

A real percentile cannot be computed from anything this repository currently
retains:

- `contextual_orchestrator/model_group.py:39-48,179-243` —
  `ModelGroupRouter.observe_success` takes `latency_seconds` per call and
  folds it into one scalar EWMA (`EWMA_LATENCY_GAIN = 0.125`, Jacobson's 1988
  SRTT gain) per model. Confirmed by direct read of the update block
  (`model_group.py:232-239`): the individual sample is never retained, only
  `state["ewma"]` is mutated. In-process memory only, lost on restart.
- `contextual_orchestrator/cost_ledger.py:767-780` — the one durable,
  queryable table (`llm_usage_records`) has no latency/duration column at
  all: `usage_record_id, created_at, workflow_run_id, request_channel,
  route_mode, provider_name, model_name, prompt_tokens, completion_tokens,
  total_tokens, cost_amount, currency_code`.
- `contextual_orchestrator/admin.py:963` renders a **hardcoded static
  string**, `"2.50s"`, next to the label "Latency P95 route threshold" —
  bound to no field in any API response. `contextual_orchestrator/orchestrator.py:813`
  (`route_p95_seconds: float = 2.5`) is a static dataclass default, never
  computed from data.
- No `percentile`/`quantile`/`p95`/`p99` computation exists anywhere in
  `contextual_orchestrator/*.py` outside those two static values and one
  unrelated quality-score bootstrap CI in `nim_benchmark.py:2350`.
- Real per-call wall-clock deltas **are** computed live, in several places,
  via `time.perf_counter()`/`time.monotonic()` — `orchestrator.py:1536,
  1973, 2025, 2033, 4836, 4898, 5232-5249` — but every consumer either
  collapses the value into the EWMA above, buries it in an unindexed
  `orchestration_records.payload` JSON blob (`orchestrator.py:3602-3609`),
  or exports it as an OTel span attribute (`telemetry.py:67`) whose
  retention is external and unverifiable from this repository.

**This ADR cannot be run today.** The instrumentation (the timing calls
themselves) already exists; the retention does not. Phase 0 below is a real,
separate prerequisite, not a formality.

## Non-goals

- **Not an enforcement change.** This ADR does not touch
  `ModelClient.chat`/`stream_chat`, does not reintroduce
  `MIN_MODEL_TIMEOUT_SECONDS`/`MAX_MODEL_TIMEOUT_SECONDS`, and does not
  resolve the four enforcement-correctness findings the owner cited when
  closing `#1010` (the local-queue call path ignoring the override,
  passthrough/tool-call requests bypassing it, a failed persistence write
  leaving the live timeout mutated, and admin-refresh races misreporting
  audit state). Those are bugs in `#1010`'s *wiring*, orthogonal to whether
  the *number* being wired is evidence-based. Reusing `#1010`'s UI/persistence
  does not inherit a pass on those bugs; whatever PR re-wires enforcement
  must fix them on their own evidence.
- **Not a second timeout-decision path.** It never inspects model, provider,
  or reasoning-profile identity to decide *whether* to impose a timeout —
  that decision stays exactly where `contextual-orchestrator#971` puts it
  (an explicit caller/operator choice, always). This ADR only computes a
  number an operator *could* choose to enter into that existing choice.

## Decision

Four phases. Phases 1-3 are pure computation and can be implemented and
tested independently of Phase 0 (against synthetic/fixture data), but cannot
run against real traffic until Phase 0 ships.

```mermaid
flowchart TD
  P0["Phase 0: latency telemetry\n(duration_ms, ttft_ms, completed,\nreasoning_effort_profile per call)"] --> P1
  P1["Phase 1: per-model quantile estimate\n(sample-size gated, HD/trimmed-HD)"] --> Gate{n meets floor\nfor target percentile?}
  Gate -- yes --> Out1[suggested_timeout_seconds\n+ basis = own-model estimate]
  Gate -- no --> T2{coarser aggregate\n(profile tier / provider)\nmeets floor?}
  T2 -- yes --> Out2[suggested_timeout_seconds\n+ basis = borrowed aggregate]
  T2 -- no --> Out3["suggested_timeout_seconds = null\n(no evidence -> no suggestion,\nmatches org no-fixed-timeout default)"]
  P1 -.reasoning-profiled model.-> P2["Phase 2: TTFT/TPOT decomposition\n+ non-convergence rate"]
  P2 --> Out1
  P2 --> Out2
  Out1 --> Admin[Phase 3: admin surface\n(read-only suggestion;\nadmin opts in via existing\nset_model_timeout path)]
  Out2 --> Admin
  Out3 --> Admin
```

### Phase 0 (prerequisite): build the latency telemetry that does not exist

Add a durable, queryable table — e.g. `llm_latency_samples` (new table, or a
sibling of `llm_usage_records` keyed the same way) — populated from the exact
`time.perf_counter()`/`time.monotonic()` values already computed at the call
sites listed above. No new instrumentation is invented; only retention is
added. Minimum columns:

- `model_name`, `provider_name`, `created_at`.
- `duration_ms` — the full call's wall-clock latency, the same value already
  fed into `ModelGroupRouter.observe_success`.
- `ttft_ms` (nullable) — captured only on the streaming path
  (`stream_chat`), where a first-token timestamp is actually observable; left
  null for non-streaming and batch calls rather than backfilled with a guess.
- `completed` (bool) and, when false, a `termination_reason` (e.g.
  `provider_error`, `caller_cancelled`, `budget_exhausted`) — so a call that
  never finished is never silently averaged in as if it were a normal
  observation.
- `reasoning_effort_profile` (nullable, references ADR 0021's declared
  profile catalog) — this is how a reasoning-capable call is distinguished
  from an ordinary one, using the operator-declared profile ADR 0021 already
  established, not a hand-maintained model-name list (consistent with
  `#971`'s "no hand-maintained reasoning-model list" rule).

Retention: a bounded rolling window per `(model_name, reasoning_effort_profile)`
key — e.g. the most recent 2,000 samples — kept as raw values, not a
compressed sketch, for the reasons in "Alternatives rejected" below.

### Phase 1: sample-size-gated quantile estimation

A percentile is not trustworthy below a sample-size floor that depends on
*which* percentile is being estimated — the expected count of observations at
or beyond a quantile is `n(1-p)` (binomial mechanics; David & Nagaraja, 2003;
Gibbons & Chakraborti, 2003), so p99 needs far more data than p50 for the
same confidence. Applied to skewed, latency-shaped data specifically (Ialongo,
2019a, 2019b):

| Target percentile | Minimum `n` before trusting a direct estimate |
|---|---|
| p50 | ~20 |
| p90-p95 | ~60 |
| p99 | ~120 |
| p99.9 | not viable as a direct order-statistic estimate under roughly 1,000-10,000+ samples; requires EVT/POT extrapolation instead (Coles, 2001; Scarrott & MacDonald, 2012) |

When `n` meets the floor, use the **Harrell-Davis estimator** (Harrell &
Davis, 1982) — a weighted combination of *all* order statistics — rather than
a naive linear-interpolation percentile (Hyndman & Fan's, 1996, "Type 7,"
most libraries' default): Harrell-Davis is materially more efficient at
modest `n` for light/moderate-tailed distributions and the *center* of
heavy-tailed ones (Akinshin, 2021). For p99-class targets specifically, use
the **trimmed Harrell-Davis** variant (Akinshin, 2022) instead of plain HD:
Akinshin's own efficiency analysis shows plain HD is *less* efficient than
the naive estimator specifically in the tails of heavy-tailed distributions —
exactly where p99 sits for right-skewed LLM latency — so the allocator must
not use unweighted HD unmodified at the extreme end.

For p99.9-class targets, or any percentile whose own-model `n` is large but
still short of the order-statistic floor, fit a Generalized Pareto tail to
exceedances over a data-rich lower threshold (e.g. this model's own empirical
p90) and extrapolate — the Peaks-Over-Threshold method (Coles, 2001; de Haan
& Ferreira, 2006). This is deferred to a later slice (see "Alternatives
rejected"); Phase 1 ships p50/p90/p95/p99 support first.

### Phase 2: TTFT/TPOT decomposition, and where it stops being useful

The standard decomposition — `TTLT = TTFT + (TBT x tokens_generated)` — is
both the dominant research framing (Agrawal et al., 2025) and, as of 2026,
first-party production diagnostic tooling (Microsoft, 2026, Azure OpenAI's
identical formula). `ttft_ms`/`duration_ms` from Phase 0 let the allocator
compute this split *diagnostically* — so an admin can see whether a model's
slowness is queueing/prefill-bound or decode-bound.

It is **not** used as the value fed into the percentile math itself. Wang et
al. (2024/2025) show that naive SLO metrics built directly on this
decomposition are gameable server-side (a server can "manually delay the
delivery of some tokens" or "actively abandon requests that do not meet
SLOs" and improve the reported metric while user experience gets worse). The
allocator's percentile input is always the real, full-call `duration_ms`
sample — end-to-end, unreconstructed — precisely to avoid rewarding a
provider for gaming a synthetic TTFT+TPOT target.

**Reasoning-capable models break the decomposition outright**, not just
its accuracy. For a reasoning model, TTFT covers an internal chain-of-thought
trace whose length is a property of the problem's difficulty and the model's
own RL-induced stopping behavior (DeepSeek-AI, 2025), not the prompt's token
count — collapsing the clean prefill/decode split the formula assumes. More
concretely, reasoning-model completion time is empirically **bimodal**, not
merely heavy-tailed: Oladri, Jawahar, and Mohamed (2026) find
DeepSeek-R1-Distill-Qwen-7B on AIME either converges within budget (62.0% of
generations, 90.3% accuracy) or exhausts the budget without concluding
(38.0%, 6.6% accuracy) — a request is either answered well or burns the full
allowance for a near-worthless answer, with almost no useful middle ground.
Li et al. (2025) corroborate this pattern more broadly across reasoning-model
serving (memory fluctuation, "straggler" requests, output-dependent rather
than prompt-length-dependent running time), and Marjanović et al. (2025)
document a related failure mode — "rumination," looping on an
already-explored framing — that inflates latency without inflating quality.

Design consequence, for any model carrying a reasoning-effort profile (ADR
0021):

1. The allocator still computes the same percentile the same way — it is
   still a latency distribution, and Phase 1's math does not change.
2. It additionally computes and surfaces the empirical **non-completion
   rate** at the model's configured budget, from Phase 0's
   `completed=False, termination_reason=budget_exhausted` samples.
3. The admin-facing suggestion for a reasoning-profiled model is always shown
   *alongside* that non-completion rate, with a fixed caption pointing at the
   bimodality finding, rather than as a bare number with false precision. No
   paper establishes a general numeric "flag if fewer than X% converge"
   threshold — Oladri et al. (2026) is one model on one benchmark — so this
   design deliberately does not invent one; it always shows both figures and
   leaves the judgment to the operator, which is the honest position given
   what the literature actually supports.
4. None of this changes *enforcement*. Per `#971`'s universal contract, no
   automatic per-reasoning-model branch exists in the request path; this is
   display-only guidance feeding the same optional override field every
   other model's suggestion feeds.

### Phase 3: fallback ladder when a model's own sample count is too small

1. **Tier 1 — own-model estimate.** When the model's own `n` (within its
   `reasoning_effort_profile` segment) meets Phase 1's floor for the
   requested percentile, use the Harrell-Davis/trimmed-HD estimate directly.
2. **Tier 2 — borrow from a coarser, better-populated aggregate.** When the
   model's own `n` is below the floor but a coarser grouping — the same
   `reasoning_effort_profile` tier across models, or the same provider — has
   enough samples, compute the suggestion from that aggregate instead and
   label it as borrowed. This is a direct, honestly-labeled inference from
   the sample-size literature above (small-`n` coverage degrades per
   Ialongo, 2019a/2019b; CI width blows up per the binomial mechanics in
   David & Nagaraja, 2003) rather than an independently citable single-paper
   rule for this exact operational case — flagged as such rather than
   oversold.
3. **Tier 3 — no suggestion.** When not even a coarser aggregate has enough
   samples (a brand-new model or provider with negligible traffic), the
   suggested value is `null` — "not enough evidence to suggest anything
   yet." This is not a contradiction of Tier 1/2's preference to widen
   rather than null-out; it is what widening degenerates to when there is
   *nothing* to widen from. It also happens to be exactly this org's
   already-adopted default: no fixed wall-clock timeout unless an operator
   explicitly sets one (`.github` ADR-0003 2026-08-31 amendment;
   `contextual-orchestrator#971`). Fail-open, not fail-fixed — this design
   never invents a conservative constant as a last resort.

## Admin surface: what changes for `#1010`'s UI/persistence

Add one read-only, computed block per model to the existing (or a revived)
per-model-timeout admin panel:

- `suggested_timeout_seconds` (nullable) and `suggested_basis` (a short,
  human-readable string, e.g. `"p99 trimmed-HD, n=143, own-model"` /
  `"p95 HD, borrowed from provider tier (own n=12 < floor 60)"` /
  `"insufficient data"`).
- For reasoning-profiled models, `non_convergence_rate` displayed next to the
  suggestion, per Phase 2.

This block is **informational only** — it is never written to
`override_timeout_seconds` automatically. An admin who wants to accept it
clicks "use suggested value," which writes through the *exact same*
KV-persisted, audited path `#1010` already built
(`TaskOrchestrator.set_model_timeout` -> `_StateStore`'s
`"model_timeout_override"` keyed kind -> `_append_audit_event`). This is the
selective reuse the owner's closing comment names — the UI/persistence
machinery is unchanged; only the number an admin is looking at when they
decide to use it is now evidence-based instead of typed from nothing.

No platform-wide `MIN`/`MAX` ceiling is reintroduced. `#1010`'s rejection was
specifically about a research-free `1`/`14400` bound, and none of the three
research tracks behind this ADR establish any universal bound, evidence-based
or otherwise — nor does one need to exist now that `#971` makes "no bound" the
library default. If any input validation is wanted at all, it should be a
basic positivity/sanity check on operator entry, not a policy ceiling, and
belongs to whichever future PR re-wires enforcement, not to this ADR.

## Alternatives rejected

- **A fixed constant scaled by "typical" model class** (what `#1010` did):
  rejected outright — it is the design already rejected once, for exactly
  this reason.
- **Feeding the TTFT+TPOT reconstructed budget directly into the timeout
  formula**: rejected because Wang et al. (2024/2025) demonstrate this exact
  metric shape is gameable server-side; using raw end-to-end `duration_ms`
  samples for the percentile itself removes that incentive, at the cost of
  losing the (gameable) diagnostic granularity — an acceptable trade since
  Phase 2 still exposes the TTFT/TPOT split for diagnosis, just not for the
  timeout math.
- **One fixed bimodality/reasoning-exception threshold** (e.g. "flag if
  <70% converge"): rejected — no cited paper establishes a general numeric
  cutoff; encoding one would be exactly the unfounded heuristic this org's
  own no-heuristics rule forbids. Always surfacing the raw non-convergence
  rate instead of a threshold-derived flag avoids inventing an unsupported
  number.
- **A streaming sketch (t-digest / Circllhist) for Phase 0 storage, from day
  one**: deferred, not rejected. `ponytail`: raw bounded rolling arrays
  (2,000 samples/key) are simpler, and this repository's current per-model
  call volume does not yet justify a mergeable sketch structure; upgrade
  path is documented and cited (Dunning & Ertl, 2019; Hartmann &
  Schlossnagle, 2020) for if/when a model's window becomes a measured memory
  problem.
- **EVT/GPD tail fitting as the default p99.9 estimator from day one**:
  deferred. Scarrott and MacDonald's (2012) own review of POT threshold
  selection has no single settled minimum exceedance count — "tens to
  roughly 100" is the literature's rough consensus, not a theorem — so
  building this before Phase 0 has enough traffic history to make it
  meaningful is premature complexity; Tier 2 borrowing covers the interim,
  and p99.9 support is explicitly out of scope for the first implementation
  slice.

## Consequences

- Nothing in this ADR is runnable today. Phase 0 (schema + retention) is a
  real, separate implementation PR with its own tests, and Phases 1-3's math
  has nothing to compute from until it ships. This ADR states that plainly
  rather than implying the data already exists.
- ADR 0021's reasoning-effort-profile catalog becomes a second consumer
  (routing was the first); any future restructuring of that catalog must
  account for this allocator's segmentation key.
- The pre-existing hardcoded `"2.50s"` string in `admin.py`'s Settings view
  and the static `route_p95_seconds: float = 2.5` default on
  `OrchestrationPolicy` are now visibly misleading once this ADR is known —
  flagged here as a real, pre-existing, unrelated defect for a future PR to
  fix; not touched by this design-only ADR to keep its diff reviewable.
- No behavior changes for any existing caller. This ADR adds new tables,
  computation, and an admin display only; `ModelClient.chat`/`stream_chat`
  and every existing test double are untouched.

## Open questions the literature does not settle

- **No citable minimum exceedance count for EVT/POT fits.** Scarrott and
  MacDonald (2012) survey competing threshold-selection heuristics
  precisely because no single number is authoritative; Phase 1 defers
  EVT/POT entirely rather than picking one.
- **No general numeric bimodality/non-convergence threshold for reasoning
  models.** Oladri et al. (2026) is one model (DeepSeek-R1-Distill-Qwen-7B)
  on one benchmark family (AIME/GSM8K/MATH-500); whether the 62%/38% split
  generalizes across reasoning model families and task domains is unverified
  by anything found in this research. Phase 2 always surfaces the raw rate
  rather than a derived flag for exactly this reason.
- **No production system documents deriving a timeout *value* from observed
  latency percentiles.** vLLM, TensorRT-LLM, SGLang, AWS Bedrock, Azure
  OpenAI, and OpenAI's own documentation either hardcode a constant or leave
  it to the operator; even NVIDIA Dynamo's SLA-based Planner — the most
  sophisticated documented system found — uses profiling to size capacity
  *against* an operator-supplied target, not to compute the target itself.
  This ADR is not adapting an existing methodology; it is building one, and
  should be reviewed with that in mind.
- **The Harrell-Davis-vs-t-digest choice has no head-to-head production
  evidence.** Circonus's own production latency-monitoring literature
  (Hartmann, 2019; Hartmann & Schlossnagle, 2020) uses bounded-error
  histogram sketches, not Harrell-Davis, for exactly this class of problem;
  no source found shows HD adopted in a production latency-SLO monitoring
  system. Phase 0's choice to start with raw rolling-window samples (feeding
  HD/trimmed-HD directly) rather than a sketch is this design's own
  engineering trade-off, not something the cited literature validates either
  way at this repository's current traffic volume.
- **Tier 2's "borrow from a coarser aggregate" rule is this design's own
  inference**, not an independently citable operational rule for the
  LLM-timeout use case specifically — it follows from the small-sample
  coverage results (Ialongo, 2019a, 2019b) and CI-width mechanics (David &
  Nagaraja, 2003) by direct implication, but no single paper states this
  exact fallback for this exact problem. Reviewers should treat it as
  reasoned engineering judgment built on cited statistics, not as itself a
  citation.

## References

Agrawal, A., Kedia, N., Agarwal, A., Mohan, J., Kwatra, N., Kundu, S.,
Ramjee, R., & Tumanov, A. (2025). *On evaluating performance of LLM
inference serving systems*. arXiv. https://arxiv.org/abs/2507.09019

Akinshin, A. (2021). *Efficiency of the Harrell-Davis quantile estimator*
[Blog post]. https://aakinshin.net/posts/hdqe-efficiency/

Akinshin, A. (2022). Trimmed Harrell-Davis quantile estimator based on the
highest density interval of the given width. *Communications in Statistics
- Simulation and Computation*. (Preprint: arXiv:2111.11776)

Amazon Web Services. (n.d.). *Prevent LLM read timeouts in Amazon Bedrock*.
AWS re:Post Knowledge Center. Retrieved September 2, 2026, from
https://repost.aws/knowledge-center/bedrock-large-model-read-timeouts

Coles, S. (2001). *An introduction to statistical modeling of extreme
values*. Springer.

David, H. A., & Nagaraja, H. N. (2003). *Order statistics* (3rd ed.). Wiley.

de Haan, L., & Ferreira, A. (2006). *Extreme value theory: An introduction*.
Springer.

DeepSeek-AI. (2025). *DeepSeek-R1: Incentivizing reasoning capability in
LLMs via reinforcement learning*. arXiv. https://arxiv.org/abs/2501.12948

Dunning, T., & Ertl, O. (2019). *Computing extremely accurate quantiles
using t-digests*. arXiv. https://arxiv.org/abs/1902.04023

Gibbons, J. D., & Chakraborti, S. (2003). *Nonparametric statistical
inference* (4th ed., rev. and expanded). Marcel Dekker.

Harrell, F. E., & Davis, C. E. (1982). A new distribution-free quantile
estimator. *Biometrika, 69*(3), 635-640. https://doi.org/10.1093/biomet/69.3.635

Hartmann, H. (2019, October 4). *Quantiles* [Blog post].
https://www.heinrichhartmann.com/archive/quantiles.html

Hartmann, H., & Schlossnagle, T. (2020). *Circllhist - A log-linear
histogram data structure for IT infrastructure monitoring*. arXiv.
https://arxiv.org/abs/2001.06561

Hyndman, R. J., & Fan, Y. (1996). Sample quantiles in statistical packages.
*The American Statistician, 50*(4), 361-365.
https://doi.org/10.1080/00031305.1996.10473566

Ialongo, C. (2019a). Confidence interval for quantiles and percentiles.
*Biochemia Medica, 29*(1), Article 010101.
https://doi.org/10.11613/BM.2019.010101

Ialongo, C. (2019b). Confidence interval of percentiles in skewed
distribution: The importance of the actual coverage probability in
practical quality applications for laboratory medicine. *Biochemia Medica,
29*(3), Article 030101. https://doi.org/10.11613/BM.2019.030101

Li, Q., Wu, J., Liu, X., Wang, Y., Li, Z., Tang, Z., Chen, Y., Shi, S., &
Chu, X. (2025). *Reasoning language model inference serving unveiled: An
empirical study*. arXiv. https://arxiv.org/abs/2510.18672

Marjanović, S. V., Patel, A., Adlakha, V., Aghajohari, M., BehnamGhader, P.,
Bhatia, M., Khandelwal, A., Kraft, A., Krojer, B., Lù, X. H., Meade, N.,
Shin, D., Kazemnejad, A., Kamath, G., Mosbach, M., Stańczak, K., & Reddy, S.
(2025). *DeepSeek-R1 Thoughtology: Let's think about LLM reasoning*. arXiv.
https://arxiv.org/abs/2504.07128

Microsoft. (2026). *Azure OpenAI in Microsoft Foundry Models performance &
latency*. Microsoft Learn.
https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/latency

NVIDIA. (n.d.). *SLA-based planner*. NVIDIA Dynamo Documentation. Retrieved
September 2, 2026, from
https://docs.nvidia.com/dynamo/latest/planner/planner_intro.html

Oladri, R., Jawahar, N., & Mohamed, A. (2026). *Token budget saturation and
mechanistic early-detection of reasoning non-convergence in
chain-of-thought models*. arXiv. https://arxiv.org/abs/2607.21433

OpenAI. (n.d.). *Flex processing*. OpenAI API documentation. Retrieved
September 2, 2026, from
https://developers.openai.com/api/docs/guides/flex-processing

Scarrott, C., & MacDonald, A. (2012). A review of extreme value threshold
estimation and uncertainty quantification. *REVSTAT - Statistical Journal,
10*(1), 33-60.

Wang, Z., Li, S., Zhou, Y., Li, X., Zhang, Z., Cam-Tu, N., Gu, R., Tian, C.,
Chen, G., & Zhong, S. (2024). *Revisiting service level objectives and
system level metrics in large language model serving*. arXiv.
https://arxiv.org/abs/2410.14257
