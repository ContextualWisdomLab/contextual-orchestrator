# Method-fidelity audit — 2026-09-17

Scope: line-by-line comparison of the implementation against the cited source
for `model_group.py`, `endpoint_race.py`, `psychometric_routing.py`,
`benchmark_priors.py`, and the Fugu/TRINITY/Conductor architectural citations
in `docs/architecture.md`. This supersedes a prior pass that only confirmed
the cited papers exist without comparing them against the code.

**Headline finding: no method-fidelity code fix was required.** Every
requested check (update-rule/gain constants, whether priors update from
observed outcomes, state persistence across restarts, exploration vs.
exploitation, and attempt/timeout budgets) resolves to either a faithful
implementation or an already-disclosed, already-ADR'd intentional divergence.
One correction to the audit brief itself: **`endpoint_race.py` is not a
Jacobson (1988) implementation.** Its cited sources are Dean & Barroso (2013,
hedged requests) and Gardner et al. (2017, redundancy-d); Jacobson is only
cited for `model_group.py`'s latency EWMA. No RED→GREEN fixes or new PRs were
opened; where a divergence exists it is already recorded in an existing ADR
or doctoring record, cited below instead of duplicated.

## Table: paper claim vs. implementation

| # | Component | Paper claim (locator) | Implementation (file:line) | Verdict |
|---|---|---|---|---|
| 1 | `model_group.py` | Laplace (1774) rule of succession / Gelman et al. (2013) §2.4: uniform Beta(1,1) prior, posterior mean `p = (s+1)/(s+f+2)` | `BETA_PRIOR_SUCCESS_COUNT = BETA_PRIOR_FAILURE_COUNT = 1.0` (`model_group.py:43-44`); `alpha += 1.0` on success (`:233`), `beta += 1.0` on failure (`:267`); `stability = alpha / (alpha + beta)` (`:310`, `:337`) | **Faithful** |
| 2 | `model_group.py` | Prior must be distinct from, and additive with, observed evidence (Gelman et al., conjugate-update convention) | `update_prior()` (`:143-177`) shifts `alpha`/`beta` by exactly `Δprior`, leaving `success_count`/`failure_count` (`:345-346`) bit-identical; `benchmark_priors.resolve_quality_prior` (`benchmark_priors.py:136-149`) and `openrouter_uptime.py:130-131` are the two callers | **Faithful** — priors *do* update from newly observed outcomes (every `observe_success`/`observe_failure` call), and prior replacement never overwrites observed counts |
| 3 | `model_group.py` | Jacobson (1988) SRTT estimator: `SRTT ← (1-g)·SRTT + g·sample`, `g = 1/8` | `EWMA_LATENCY_GAIN = 0.125` (`:40`); update at `:236-240`: `(1.0 - gain) * ewma + gain * clamped` | **Faithful** |
| 4 | `model_group.py` | Same EWMA form applied to a second signal (Jacobson's estimator is general-purpose, not RTT-specific) | Tokens-per-second EWMA, same gain, `:241-248` | **Faithful** |
| 5 | `model_group.py` | *(not claimed)* Jacobson's companion RTTVAR estimator (`gain 1/4`) and `RTO = SRTT + 4·RTTVAR` | Not implemented anywhere in the repo (`grep -r RTTVAR` returns zero hits) | **Missing relative to the full paper, but not a citation violation** — every doc that cites Jacobson (`model_group.py:14-20`, `docs/model-group-product-technical-spec.md:175`, `docs/planning/adrs/0032…:135`) scopes the citation to "the EWMA latency estimator" only, never to RTO/timeout. Nothing in the codebase claims adaptive-timeout fidelity to Jacobson. No fix needed; no ADR needed because no claim was made to retract. |
| 6 | `model_group.py` | *(engineering addition, not from the paper)* floor under the latency divisor | `MIN_ROUTING_LATENCY_SECONDS = 1e-3`; raw sample clamped before feeding the EWMA (`:210`) | **Disclosed divergence** — module docstring (`:46-48`) states this is a divide-by-near-zero guard, not a claim about matching Jacobson's raw-sample behavior. No PR needed. |
| 7 | `model_group.py` | Score composition — *(not from any cited paper; ADR 0032 calls this "a gateway design decision, not a claim reproduced from the cited routing studies")* | `score = stability / max(ewma, floor)` (`_score_locked`, `:304-316`) | **Faithful to its own documented design**, not a paper reproduction — consistent with `docs/planning/adrs/0032-model-group-cost-aware-discovery.md:20` |
| 8 | `model_group.py` (state persistence) | *(operational choice, ADR'd)* | `ModelGroupRouter` is pure in-memory (`self._members: dict`, `__init__`, `:96-102`); no load/save. `docs/planning/adrs/0032-…:` *"The observation ledger intentionally resets on process restart: persisting it without a measurement horizon would let stale provider incidents dominate current routing."* | **Intentional, already ADR'd** — matches the stated design; not a bug |
| 9 | `model_group.py` (exploration vs. exploitation) | *(none cited — this is a posterior-mean point estimate, not a bandit paper)* | `ranked_member_ids` sorts by `-score` (`:284-287`), pure greedy/exploitative, no Thompson sampling or ε-greedy anywhere in `model_group.py`, `orchestrator.py`, or the ADRs (`grep -rn "explor\|bandit\|Thompson"` = no hits) | **Faithful** — no exploration is claimed by any citation for this component, so pure exploitation is not a divergence |
| 10 | `endpoint_race.py` | Dean & Barroso (2013), *The Tail at Scale*: hedged requests reduce tail latency by duplicating work to equivalent replicas | `race_first_valid` (`:78-165`) submits **every** attempt concurrently at `t=0` (`:123-126`), not a delayed hedge after a primary-latency percentile | **Disclosed divergence** — `docs/doctoring/equivalent-endpoint-racing.md`: *"Dean and Barroso… motivate this mechanism but does not… determine a hedge delay."* The shipped `immediate_race` policy is closer to Gardner et al. (2017) "redundancy-d" (clone-all) than to a true delayed hedge; the doc says so explicitly. No fix needed. |
| 11 | `endpoint_race.py` | Gardner et al. (2017), *Redundancy-d*: bound duplicate work by a fixed replication factor, not unbounded fan-out | `max_concurrency` must be `>= len(attempts)` and `>= 2` (`:93-96`); `EndpointEquivalenceContract` requires an operator-reviewed equivalence proof before any two endpoints may race (`:33-54`) | **Faithful** |
| 12 | `endpoint_race.py` | Timeout / attempt budget — task brief assumed Jacobson RTO; actual design is an operator-configured static deadline (`docs/doctoring/model-timeout-policy-evidence.md`) | `deadline_seconds` is caller-supplied; callers pass `self.client.timeout`, a fixed configured value (`orchestrator.py:8841`, `:9026`), not derived from `model_group`'s EWMA/variance | **Correctly attributed, not a Jacobson claim** — no RTT/RTTVAR-based adaptive timeout is cited anywhere for this path, so there is nothing to falsify. `model-timeout-policy-evidence.md` is the live doctoring record for this timeout's own (separate, in-progress) hardening work. |
| 13 | `endpoint_race.py` | Deterministic tie-break, safe cancellation of losers, no silent budget truncation | Simultaneous completions resolved by declaration order (`:141`, sorted by original index); every loser gets `cancelled` or `safe_drain` provenance (`:148-154`); `TimeoutError` raised explicitly on deadline exhaustion (`:136-140`), never a silently shortened result | **Faithful** |
| 14 | `psychometric_routing.py` | Jeon, Jin, Schweinberger & Baugh (2021): parameter estimation for **unidimensional and multidimensional** logistic IRT models | `factor_id = np.zeros(len(item_keys), dtype=int)` (`:160`) selects the paper's explicitly-supported unidimensional case; the actual MLSRM parameter estimation is delegated to the external `fast_mlsirm` native package (out of this repo's scope) | **Faithful** — the paper's title itself covers the unidimensional case chosen here; this module's fidelity duty is limited to correct matrix/factor construction and consuming the estimator honestly, which it does |
| 15 | `psychometric_routing.py` | Fail-closed on non-convergence or missing evidence (no fabricated rank) | `if result.convergence_status != "converged": return` (`:169-170`); broad `except (ImportError, RuntimeError, TypeError, ValueError): return` (`:183-186`) leaves `self._scores` empty rather than inventing a score | **Faithful** |
| 16 | `psychometric_routing.py` | Cold-start nearest-item lookup — *(no paper cited for the cosine step; it is this module's own bridge from a new prompt to the nearest fitted item)* | `_cosine` (`:188-198`) is a standard cosine similarity, tie-broken by `(similarity, stored_id)` (`:103`) for determinism | **Faithful to its own documented contract** |
| 17 | `psychometric_routing.py` (state persistence) | *(operational choice, ADR'd)* | Unlike `model_group.py`, this evidence **does** survive restart: `orchestrator.py:_reload_state` replays `psychometric_observation` rows (`:8261-8268`) into `observe_context_id`; `_observe_contextual_quality` persists each new observation (`:8267-8285`) | **Faithful, and consistent** — persistence policy differs by design between the transport/quality ledgers (reset) and the judged-quality evidence (durable), and both are documented in their respective call sites |
| 18 | `benchmark_priors.py` | Bradley, R. A., & Terry, M. E. (1952): Arena Elo is itself a Bradley-Terry-model output (grounds the *rating scale*, not a fusion formula) | `_ARENA_ELO` values are consumed as-is (`:61-73`); the citation is only invoked to justify treating the published Elo number as a valid paired-comparison estimate, which is accurate to how Chiang et al. (2024) compute it | **Faithful** — no equation from Bradley-Terry is claimed to be reimplemented here, and none is |
| 19 | `benchmark_priors.py` | Mass-preserving prior redistribution — *(this repo's own derivation, explicitly self-labeled as such in the module docstring, not a paper claim)* | `_center_scale` (median/MAD standardization, `:90-105`), equal-weight average of two z-scores (`:116-117`), `logistic(z)` (`:118-121`), then `alpha = p·budget`, `beta = (1-p)·budget` (`:147-149`) where `budget = BETA_PRIOR_SUCCESS_COUNT + BETA_PRIOR_FAILURE_COUNT` imported from `model_group.py` (`:47-54`) | **Faithful to its own documented derivation contract** (§ docstring lines 13-30); arithmetic matches the stated recipe exactly |
| 20 | `benchmark_priors.py` (prior refresh cadence) | *(operational choice)* | `_ARENA_ELO`/`_QUALITY_INDEX` are a static, dated snapshot (`:56-60`, "2025-05-03"); `resolve_quality_prior` is only invoked at `register_member` time (`orchestrator.py`'s `ModelGroupRouter(prior_resolver=resolve_quality_prior)`), not re-applied on a schedule | **Intentional, documented** — module docstring: "refresh them only alongside their provenance dates"; ongoing prior correction for *already-registered* members instead flows through the separate, live `openrouter_uptime.py → update_prior` path, not through re-running `benchmark_priors` | Not a fidelity gap: no paper claims a refresh cadence |
| 21 | `docs/architecture.md` — Fugu/TRINITY/Conductor | Sakana Fugu (route vs. conduct latency/quality split), TRINITY (Xu et al., 2025, thinker/worker/verifier), Conductor (Nielsen et al., 2025, natural-language steps + access lists) | `TaskOrchestrator.route_once` (Fugu low-latency path) vs. `TaskOrchestrator.conduct` (Fugu-Ultra path) with `WorkflowStep.access` (Conductor-style visibility) and thinker/worker/verifier/synthesizer roles (TRINITY) — `docs/architecture.md:45-113` names the exact symbols | **Faithful at the architectural-motivation level** — these are cited as design inspiration for a control-plane *shape* (route/conduct split, role names, step+access-list structure), not as specific numbered equations to reproduce. `docs/architecture.md:159` self-labels this explicitly: *"The product is not a Fugu clone."* There is no algorithmic equation from any of the three papers to falsify line-by-line; the fidelity question that applies to numbered-equation papers (Jacobson, Laplace, Bradley-Terry, Jeon et al.) doesn't apply the same way here. |

## Why no PR was opened

Every check the audit brief asked for — gain constants, whether priors update
from real outcomes, state persistence across restarts, exploration vs. pure
exploitation, and attempt/timeout budgets cutting the method short — comes
back faithful or already-disclosed:

- Gain constants (`1/8` for the EWMA, `Beta(1,1)` for the prior) match their
  cited sources exactly (rows 1, 3).
- Priors are updated from observed outcomes on every attempt (`alpha`/`beta`
  increment in `observe_success`/`observe_failure`), and prior *replacement*
  is additive/non-destructive by construction (row 2).
- State persistence is a deliberate per-ledger policy, not an oversight: the
  transport/quality ledgers reset on restart (ADR 0032, row 8) while the
  judged-quality (psychometric) evidence is durable and replayed (row 17).
  Both policies are stated in the code they govern.
- There is no exploration/exploitation tradeoff to violate: no citation for
  `model_group.py` claims a bandit algorithm, so pure greedy ranking is not a
  divergence (row 9).
- No attempt/timeout budget silently truncates a cited method: the one
  adaptive-timeout algorithm in the audit brief (Jacobson's RTO) was never
  actually claimed by any component — `endpoint_race.py`'s real citations
  (Dean & Barroso; Gardner et al.) are honored, and its use of a fixed,
  operator-configured deadline is explicitly disclosed rather than presented
  as an RTT-derived timeout (rows 10, 12).

The only candidates for a "divergence that increases latency or fallback
rate" — the missing Jacobson RTTVAR/RTO half (row 5) and the
immediate-fan-out vs. delayed-hedge gap (row 10) — are both pre-existing,
explicitly-scoped design decisions with their own doctoring records
(`docs/doctoring/equivalent-endpoint-racing.md`,
`docs/doctoring/model-timeout-policy-evidence.md`, ADR 0032). Re-litigating
those decisions (e.g., building an adaptive RTO, or a delayed hedge timer) is
a scope change beyond a fidelity audit and is intentionally left to the
in-progress timeout-policy work tracked in
`docs/doctoring/model-timeout-policy-evidence.md`.

## Verification performed

- Read `contextual_orchestrator/{model_group,endpoint_race,psychometric_routing,benchmark_priors}.py`
  in full and traced every constant/update site referenced above to a line
  number.
- Grepped the whole tree for `RTTVAR`/`RTO`/`Thompson`/`bandit`/`explor` to
  confirm the absence of an adaptive-timeout or exploration implementation
  before concluding "missing" rather than missing a hidden implementation.
- Cross-checked every paper citation against `docs/papers/README.md`,
  `docs/planning/adrs/0032-model-group-cost-aware-discovery.md`,
  `docs/doctoring/measured-routing-evidence.md`,
  `docs/doctoring/equivalent-endpoint-racing.md`, and
  `docs/doctoring/model-timeout-policy-evidence.md` to determine what each
  component actually claims to reproduce, rather than assuming the audit
  brief's component→paper pairing was correct (it was not, for
  `endpoint_race.py`).
- No code was changed; no tests were run beyond the reads above, since no
  behavior change is being proposed. `tests/test_model_group.py`,
  `tests/test_endpoint_race.py`, `tests/test_psychometric_routing.py`, and
  `tests/test_benchmark_priors.py` already provide the RED→GREEN contract
  coverage referenced in rows 1-20 (46 test functions total across the four
  files as of this audit).
