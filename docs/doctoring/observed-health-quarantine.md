---
title: "Observed-outcome health quarantine for served-request candidate selection"
status: "Proposed (operator opt-in; default off)"
date: "2026-09-22"
scope: "feat/observed-health-quarantine (base origin/main 5665b0ad)"
---

# Observed-outcome health quarantine

## Problem (measured, biased sample)

Evidence source (read-only, not committed): the sanitized Noema sidecar
artifacts under
`CO-LEAD-EVIDENCE-20260920/research-support-20260921/noema-real-path-measurement-20260922/`
in the lead workspace. There are 101 runs from 8 repositories. Twelve runs sit
under the hidden `.github/` directory, which the evidence directory's own
scripts skip, so its `summary.txt` covers 89 runs. The deployed pin was
`767e67f`. **The upload step ran on `failure()` only, so this sample
over-represents failed runs; none of the numbers below are population rates.**

- Served review requests: p50 1670 s, p90 4567 s.
- RemoteDisconnected (p50 265 s) and HTTP 504 (p50 302 s) make up about 94 %
  of failed-attempt wall time.
- Within a single run, the same agent slow-failed again on 165 extra attempts
  across 36 runs. Most of these were NVIDIA NIM `deepseek-v4-flash-0731` (both
  accounts), `llama-3.2-90b-vision-instruct` and `gemma-4-31b-it`.
- The legacy breaker opens after three unweighted consecutive failures. Its
  `circuit_reset_seconds = 30` is shorter than one ~300 s failing attempt, and
  the reset zeroes the counter. This is the second and third gap recorded in
  `docs/product-technical-gap-baseline.md` (2026-09-06 amendment).

## Policy boundary: explicit operator opt-in

`docs/product-technical-gap-baseline.md` (no-heuristics boundary, 2026-09-07)
keeps automatic candidate exclusion at the legacy 3/30 policy unless an
operator supplies the decision. This change therefore ships the mechanism
behind `TaskOrchestrator(..., observed_health_quarantine=False)`.

With the flag off (the default, and what the sidecar runs today), the breaker
is behavior-identical to the legacy one: weight 1, a 30 s reset that zeroes
the counter, no failure-rate trigger, no half-open state and no demotion. The
only additions are observability: extra `circuit_opened` fields, the
`circuit_all_open_fallback` log line and the `routing_evidence.health`
snapshot.

The values below are repository-proposed and backed only by the replay in
this document. Enabling them, and choosing how the sidecar passes the flag
(CLI or KV bootstrap, following the `rate_limit_wait_seconds` precedent), is
an owner decision. #1000, #911 and #1082 still own the broader routing repair.

## Design (flag on)

The breaker ledger already sits in front of candidate selection:
`_failover_candidates` filters with `_circuit_open` before any attempt. The
mechanism therefore extends that ledger rather than adding a second breaker.

| Concern | Behavior |
| --- | --- |
| Signal | Real served-request outcomes. Every existing `_record_failure` / `_record_success` call site feeds the ledger. Where the exception is in hand (`_invoke`, `stream_route`, and the explicit and virtual passthrough loops), the call passes `failure_class=classify_health_failure(exc)`. The launcher preflight is not duplicated. |
| Failure class | `slow_transport`: `provider_timeout` or `provider_connection_error`, status 408/502/504, or a raw timeout, reset, `RemoteDisconnected` or `URLError`. `fast`: everything else. Call sites that pass no class count as `unclassified` with weight 1. 413 and passthrough 429 never reach the ledger, the same as before. |
| Demotion | Once a member's latest failure is slow, `_failover_candidates` keeps it eligible but stable-sorts it behind members without a recent slow failure. The result of request N therefore changes the order for request N+1. A single failure never excludes a member. |
| Quarantine | The breaker opens when any of these holds: (a) the weighted consecutive score (slow = `slow_failure_weight` 2.0, else 1.0) reaches `circuit_failure_threshold` 3, which means two slow failures or three fast ones; (b) at least 6 of the last 10 outcomes are recorded and the failure rate is at least 0.6 (a single success no longer erases the evidence); (c) the half-open probe fails. |
| Cooldown | A trip that involved a slow failure lasts `slow_failure_cooldown_seconds` (360 s, longer than the longest observed slow failure of 302.3 s). A trip from fast failures only uses `circuit_reset_seconds` (30 s). Each half-open failure doubles the cooldown, capped at `circuit_max_cooldown_seconds` (3600 s). Any success resets the escalation level. Exclusion is never permanent. |
| Half-open / recovery | When the cooldown expires, the member becomes eligible again but stays demoted, so it is probed only after healthy members. A success clears the state and logs `circuit_recovered`. A failure re-opens the breaker immediately with the escalated cooldown. |
| Never empty | If every eligible member is open, `_failover_candidates` returns all of them, least-recently-failed first, and logs WARNING `circuit_all_open_fallback candidate_count=N selected_agent_id=... request_id=...`. With the flag off, the legacy ranked order is kept and only the log line is added. The embedding path's explicit 503 when all members are open (`_capability_agents`) is unchanged. However, the flag-on failure-rate and half-open triggers apply to every `_record_failure` caller, including `_record_embedding_failure`, `_record_race_attempt` and synthesis repair. |
| Metrics | WARNING `circuit_opened ... reset_seconds=<cooldown> failure_class=... trigger=consecutive|failure_rate|half_open_failure request_id=...`; INFO `circuit_half_open`, `circuit_recovered`; DEBUG `circuit_failure ... failure_class=...`. `circuit_health_snapshot()` holds bounded per-member fields: state, model, provider, counts, class, cooldown, remaining, window rate and open count. It is exposed at `admin_state()["routing_evidence"]["health"]`; `test_measured_routing_evidence` pins the key set. No prompt text or provider body text is included. |
| Concurrency | All ledger reads and writes happen under `_circuit_lock`. Concurrent failures open the breaker exactly once (tested with 16 threads). |
| Restart | State is in memory only. After a process restart, every member starts unquarantined and undemoted. Each Noema sidecar is a fresh process, so learning is scoped to one run. |
| Unchanged | Model timeouts (the default null timeout stays), retry and replay authorization, 413/429 handling and model-policy defaults are all untouched. The class only weights health; it never authorizes a retry. |

Compatibility note: `_circuit_open` now tests `opened_at` instead of
`failures >= threshold`. With the flag off the two tests are equivalent,
because every failure weighs 1. `_circuit` entries keep their exact legacy
shape (`{"failures", "opened_at"}`). The new state lives in `_circuit_health`.

## RED / GREEN

- New contracts: `tests/test_observed_health_quarantine.py`, 10 tests. Nine
  cover the enabled path; one pins that the default stays legacy 3/30.
- RED on unmodified `origin/main` `5665b0ad`: collection fails with
  `ImportError: cannot import name 'classify_health_failure'`. To get a
  behavioral RED, the import was removed and the original nine tests were
  re-run: 9 failed. The key assertion was
  `test_served_slow_failure_demotes_agent_for_the_next_request`:
  `['slow_worker', 'steady_worker'] != ['steady_worker', 'slow_worker']`,
  meaning request N+1 still tried the member that had just slow-failed.
- GREEN: `python3 -m pytest tests/test_observed_health_quarantine.py tests/test_measured_routing_evidence.py -q -W error`.
- Full `pytest tests` (non-strict) on base and head: the only difference was
  `test_admin_state_exposes_both_routing_ledgers`, which pinned
  `{"transport", "quality"}` and is updated for the additive `health` key.
  A second full run also failed
  `test_provider_error_taxonomy.py::test_invoke_preserves_final_classified_failure_across_candidates`.
  That test is a wall-clock rate-limit-wait flake: it failed 1 of 4
  isolated runs on unmodified `origin/main` as well. The other 200 failures
  and 31 errors are identical on `origin/main`. They are pre-existing: a
  `cost_router` import error, `selection_design` KeyErrors, egress allowlist
  and paper-inventory contracts.
- Flag-on behavior is exercised through `_invoke` and `_failover_candidates`
  only. `route_once`, virtual-selector `proxy_completion`, `stream_route` and
  `conduct` ran only with the flag off (full suite). An end-to-end flag-on
  test belongs with the enablement decision.
- `-W error` on the 13 neighbor suites: base and head are both nonclean (81
  and 82 failing ids in one run each, with different sets). The failures are
  dominated by the pre-existing `_TemporaryFileCloser` and unclosed
  `HTTPError` ResourceWarnings owned by the HTTP resource runbook (#1140).
  They are not attributed to this change.

## Replay

`scripts/replay_health_quarantine.py` is kept under `scripts/` because that
is where the repository keeps runnable analysis. It replays each run through
a fresh `TaskOrchestrator`, running the same breaker code with an injected
clock set to the log timestamps.

- **Pairing.** Each failure line is paired with the latest open attempt of the
  same request and agent, as in `noema_phase.py`. On the 89 non-hidden runs
  this reproduces the evidence summary's served failed seconds exactly
  (92,186 s).
- **What feeds the ledger.** A served failure feeds the ledger only if the
  deployed log shows the deployed path charged it, meaning a
  `circuit_failure` line follows it. 413 is never charged. Served 429 on the
  `_invoke` path is charged.
- **Forced attempts.** An attempt that started while the deployed breaker was
  open (`circuit_opened` less than 30 s earlier, not cleared) was forced by
  the never-empty fallback or by a pinned model. The replay never counts such
  an attempt as skippable (`forced_fallback_attempts`).
- **Fidelity check.** With the flag off (`--legacy-like`), the replay skips
  **0** attempts, and all 30 of its open-state hits coincide with forced
  attempts. The check also runs the other way: the replayed `circuit_opened`
  count matches the deployed log's count exactly in 99 of 101 runs. In total
  the replay opens 64 times against 66 deployed; in the two differing runs
  the replay opens one fewer time, so it errs conservative. The replay
  therefore reproduces the deployed breaker.

```bash
python3 scripts/replay_health_quarantine.py <artifacts_dir> \
  --json docs/doctoring/observed-health-quarantine-replay-served.json
python3 scripts/replay_health_quarantine.py <artifacts_dir> --include-preflight \
  --json docs/doctoring/observed-health-quarantine-replay-preflight-whatif.json
python3 scripts/replay_health_quarantine.py <artifacts_dir> --legacy-like   # deployed default
python3 scripts/replay_health_quarantine.py <artifacts_dir> --no-demotion
```

Results for all 101 runs, served requests only, flag on
(`observed-health-quarantine-replay-served.json`):

| Metric | Value |
| --- | --- |
| Served attempts / failed seconds / slow-failure seconds | 1627 / 111,065 s / 100,261 s |
| Estimated failed seconds avoided | **36,832 s** (slow-class 36,320 s, about 36 % of served slow-failure seconds) |
| … by demotion (a member tried after a sibling that succeeded) | 35,206 s over 160 skipped attempts |
| … by quarantine exclusion | 1,626 s over 10 skipped attempts |
| Quarantine episodes | 37 (15 open-state hits were forced and not skipped) |
| False-positive episodes (the first attempt after opening would have succeeded) | **1** of 37 |
| Harmful removals (a skipped attempt was its step's eventual success) | **1** attempt in 1 request (upper bound) |

Sensitivity to `slow_failure_cooldown_seconds`, flag on, all other settings
at their defaults:

| Cooldown | Saved s | Quarantine skips | FP episodes | Harmful removals / requests |
| --- | --- | --- | --- | --- |
| 300 s | 36,832 | 10 | 1 | 1 / 1 |
| **360 s (proposed)** | 36,832 | 10 | 1 | 1 / 1 |
| 450 s | 37,090 | 13 | 2 | 3 / 3 |
| 600 s | 38,181 | 21 | 3 | 7 / 4 |
| 1200 s | 38,237 | 26 | 2 | 8 / 5 |

Other variants:

- `--no-demotion` saves 13,606 s but produces 129 episodes and 10 harmful
  removals across 7 requests. Demotion is the main lever, and it also keeps
  harm down.
- `--legacy-like` (the deployed default) saves 0 s by construction.

Preflight what-if (`--include-preflight`): launcher preflight probes
(`request_id=-`) run inside the sidecar process but call `ModelClient`
directly. No preflight failure in the 101 logs was followed by a
`circuit_failure` line, so deployment does not feed them to the ledger.

Feeding them anyway adds 24 episodes. Each one opens on the served failure
that follows a preflight slow failure: the preflight failure was strike one.
(Replayed `circuit_opened` lines show `request_id=-` only because the replay
sets no request context.) The savings do not change (36,832 s) for two
reasons. That served re-hit was itself not demote-skippable, because no
healthier sibling succeeded later in the same step. And no later served
attempt reached those members inside the cooldown. This is the unrecovered
`slow_s_on_preflight_known_bad` in the evidence `summary.txt`.

### Counterfactual limits

- A skipped attempt's outcome is never fed back into the policy, because the
  gateway would not have observed it.
- Success durations are not logged, so a success is observed at the start of
  its attempt.
- The replay cannot know which substitute the gateway would have tried after
  an exclusion. It also cannot know whether a skip under the new policy would
  instead have hit the all-open fallback. Harmful counts are therefore upper
  bounds, and saved seconds ignore any substitute cost.
- A conducted request is split into failover steps, one ending at each
  success. Demotion credit requires that a non-demoted, non-open sibling
  succeeded later in the same step.
- The ceiling is within-run repetition only, because every run starts from a
  fresh process.
- The sample is biased toward failed runs, and savings will be smaller on
  healthy runs. None of this is customer-latency evidence until served
  p50/p90 are re-measured on a deployed pin with the flag on.

## Owner decisions / open questions

1. Whether and how to enable `observed_health_quarantine` for the sidecar
   (CLI or KV bootstrap). The default stays off under the 2026-09-07
   boundary.
2. The proposed cooldown is 360 s. The corrected sweep shows 300–360 s
   dominating 600 s: slightly lower savings, but 1 harmful removal instead
   of 7. This is tuned on a biased sample.
3. On the `_invoke` path, a served 429 is still charged to the breaker as a
   fast failure (144 recorded occurrences in the replayed logs), while the
   passthrough path excludes 429 as quota. This inconsistency predates this
   change and is left as it is.
4. A persisted health ledger across restarts is not implemented, so the
   gateway starts unquarantined.

## Reference

- J. Dean and L. A. Barroso, "The Tail at Scale," *Communications of the ACM*
  56(2), 2013, doi:10.1145/2408776.2408794 (already in `docs/papers/README.md`).
  It motivates keeping slow replicas off the critical path. It does not
  establish these weights or cooldowns, which rest only on the replay above.
