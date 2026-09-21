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
behind one operator switch, which is **off by default**: the KV setting
`CONTEXTUAL_ORCHESTRATOR_OBSERVED_HEALTH_QUARANTINE` (see "Activation switch"
below), or an explicit `TaskOrchestrator(observed_health_quarantine=...)`
argument, which wins over the KV value.

With the flag off (the default, and what the sidecar runs today), the breaker
is behavior-identical to the legacy one: weight 1, a 30 s reset that zeroes
the counter, no failure-rate trigger, no half-open state and no demotion. The
only additions are observability: extra `circuit_opened` fields, the
`circuit_all_open_fallback` log line and the `routing_evidence.health`
snapshot.

The values below are repository-proposed and backed only by the replay and
synthetic measurement in this document. **The 360 s slow cooldown is an
experimental candidate supported by the 101-artifact replay (biased toward
failed runs), not a validated production constant.** Enabling the switch is
an owner decision. #1000, #911 and #1082 still own the broader routing repair.

## Design (flag on)

The breaker ledger already sits in front of candidate selection:
`_failover_candidates` filters with `_circuit_open` before any attempt. The
mechanism therefore extends that ledger rather than adding a second breaker.

| Concern | Behavior |
| --- | --- |
| Signal | Real served-request outcomes. Every existing `_record_failure` / `_record_success` call site feeds the ledger. Where the exception is in hand (`_invoke`, `stream_route`, and the explicit and virtual passthrough loops), the call passes `failure_class=classify_health_failure(exc)`. The launcher preflight is not duplicated. The two single-call picks outside the failover loop, auto-mode triage and the conduct model judge, use the same order when the switch is on: open members are skipped and demoted ones are tried last. |
| Failure class | `slow_transport`: `provider_timeout`, `provider_connection_error`, `provider_outcome_unknown` (how `ModelClient` wraps a dropped chat connection before `_invoke` sees it) or `model_timeout`; status 408/502/504; or a raw timeout, reset, `RemoteDisconnected` or `URLError`. `fast`: everything else. Call sites that pass no class count as `unclassified` with weight 1. 413 and passthrough 429 never reach the ledger, the same as before. |
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
- Flag-on behavior is exercised end to end over HTTP on all four served
  paths. See "HTTP end-to-end (four paths)" below.
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

## HTTP end-to-end (four paths)

`tests/test_observed_health_quarantine_http.py` runs the real server
(`build_server` and `POST /v1/chat/completions`) with
`observed_health_quarantine=True`. Agents are `mock://`; a controllable
in-process `ModelClient` fails the "down" agents with a slow-class 504 on
`chat`, `stream_chat` and `proxy_send_once`. Time comes from the breaker's
injected monotonic clock (`_circuit_clock`), so nothing sleeps. That clock is
patched rather than the global `time.monotonic`, so that rate-limit and
server threads keep real time.

The four paths:

- **route:** `mode=route`, which reaches `route_once`.
- **conduct:** `mode=conduct`.
- **stream:** `mode=route` with `stream=true`, which reaches `stream_route`.
- **proxy:** `orchestrator/auto` plus `response_format`. This is the only
  `/v1/chat/completions` route into `proxy_completion` (it runs
  `single_agent=False`, then conduct stages and structured synthesis
  failover). A virtual selector with only `tools` is conducted instead; the
  virtual passthrough loop is reached by direct callers.

Each path is checked for:

- (a) the next request after one slow failure does not call the demoted
  member;
- (b1) after the cooldown, the half-open probe runs and recovers
  (`circuit_half_open`, then `circuit_recovered`);
- (b2) a failed probe re-opens the breaker with twice the cooldown
  (`trigger=half_open_failure`);
- (c) an all-open pool still serves, least-recently-failed first
  (`circuit_all_open_fallback`).

One extra test covers the auto-mode triage pick, and one pins that the flag
off keeps the legacy order.

**RED at `56276d65`**, with the proxy case already on the structured path:
5 failed, 13 passed. The failures were:

- `demotes[conduct]`, `demotes[proxy]`, `recovers[conduct]` and
  `recovers[proxy]`. The conduct **model-judge** call
  (`_model_judge_verification` picks the first ranked verifier) still went to
  the demoted slow member.
- `test_auto_mode_triage_pick_follows_observed_health`. The auto-mode
  **triage** call (`_compute_triage_verdict` picks `candidates[0]`) still went
  to the demoted member.

Both picks bypass `_failover_candidates`. The first draft, which used `tools`
for the proxy case, also failed `proxy` (b2) and (c), but those were conduct
behaviors reached through the wrong route and not a proxy defect.

**Minimal fix:** `_observed_health_order()` is applied to those two single-call
picks and is a no-op when the flag is off.

**GREEN:** the new files together (`test_observed_health_quarantine.py`,
`test_observed_health_quarantine_http.py`, `test_measured_routing_evidence.py`,
`test_review_gateway.py`, `test_rate_limit_breaker_asymmetry.py`) pass under
`-W error`.

A second RED came from the sidecar measurement below. `ModelClient` wraps a
dropped chat connection as `provider_outcome_unknown` before `_invoke` sees
it, and the classifier called that `fast`. The failing assertion was
`test_wrapped_post_send_failures_stay_slow_class`:
`AssertionError: provider_outcome_unknown / assert 'fast' == 'slow_transport'`.
`provider_outcome_unknown` and `model_timeout` are now in the slow set. The
replay was unaffected, because it classifies the raw logged error types.

## Synthetic sidecar-shaped measurement

The deployed entrypoint is `ContextualWisdomLab/.github`
`scripts/ci/contextual_orchestrator_review_launcher.py` (read at `.github`
`origin/main` `e6334e229`; not modified). It calls
`configure_logging(DEBUG)` with the timestamped sidecar format, then
`register_review_credentials(os.environ)`, `ModelClient(...)`,
`TaskOrchestrator(agents, client=client)` and `serve(...)`.

`scripts/measure_health_quarantine_sidecar.py` mirrors that construction in
one process per mode. Loopback egress is blocked, so the fake provider is
patched at `ModelClient._open_provider` on a reserved `.invalid` host.
Nothing leaves the process, and the real retry loop, logging, failover,
judge and breaker all run.

- `slow_free_agent` has priority 10 and raises `RemoteDisconnected` after
  0.265 s, the evidence p50 of 265 s at a 1/1000 time scale.
- `steady_free_agent` has priority 1 and answers in 5 ms.

The script sends 8 sequential `orchestrator/free` requests, each with a
distinct prompt, and parses `http_request latency_ms` and `provider_attempt`
lines from the DEBUG log. Output:
`observed-health-quarantine-sidecar-synthetic.json`.

**This is synthetic and not provider-real.** It shows the policy's mechanical
effect on one fixed failure pattern, not customer latency.

| Mode | Σ latency_ms (8 req) | Per request (ms) | Slow-agent calls (chat / judge) | provider_attempt lines | All 200 |
| --- | --- | --- | --- | --- | --- |
| off (default) | 5626.3 | 1113.5, 839.1, 842.5, 567.2, 571.3, 567.8, 560.2, 564.7 | 3 / 16 | 35 | yes |
| on (argument) | 705.1 | 475.6, 32.0, 32.1, 33.2, 31.8, 30.8, 34.0, 35.6 | 1 / 0 | 33 | yes |
| on (KV switch, launcher-identical construction) | 684.7 | 453.5, 30.3, 30.2, 31.9, 32.0, 34.5, 33.7, 38.6 | 1 / 0 | 33 | yes |

With the flag off, the legacy breaker opened once (after the 3rd chat
failure), but the model judge kept picking the slow member: 2 structured
calls per request, 16 in total. The legacy judge pick ignores the breaker.
With the flag on, the slow member is hit once, then demoted for both the
failover loop and the judge.

## Activation switch and consumer handoff

**The one switch** is the KV (credential-registry) setting
`CONTEXTUAL_ORCHESTRATOR_OBSERVED_HEALTH_QUARANTINE`.
`TaskOrchestrator.__init__` reads it once with `get_credential`, following
the "KV, not env" rule.

- `enabled`/`true`/`on`/`1` turns the quarantine on; `disabled`/`false`/`off`/`0`
  turns it off.
- Unset means off, with source `default`.
- Any other value fails construction with a `ValueError`, so a typo cannot
  silently pick a policy.
- If the KV is unreadable, the legacy policy is kept and a WARNING is logged
  (source `kv_unavailable`).
- An explicit constructor boolean wins over the KV (source `argument`).

`review_gateway.register_review_credentials()` is the bootstrap function the
launcher already imports. It copies the setting from the bootstrap
environment into the KV, in the same way it copies the gateway token.

**Why it is deployable:** the launcher constructs
`TaskOrchestrator(agents, client=client)` without policy arguments and
already calls `register_review_credentials(os.environ)` before constructing.
Honoring the switch therefore needs no copied launcher code, only a pin bump
and one environment value.

**Why it is auditable:**

- At construction, every process logs INFO
  `observed_health_quarantine enabled=<bool> source=default|kv|argument|kv_unavailable setting=... slow_failure_cooldown_seconds=...`.
  The sidecar logs at DEBUG, so the line lands in the uploaded
  `contextual-orchestrator-sidecar.stderr.log`.
- `admin_state()["routing_evidence"]["health_policy"]` reports the switch,
  its source and every knob.
- `register_review_credentials` returns the setting name in its
  `registered` tuple.

This is covered by `test_kv_switch_is_the_single_deployable_activation_and_is_audited`
and `test_kv_switch_off_values_and_invalid_value_fail_closed`.

**Consumer handoff** (for `ContextualWisdomLab/.github`; not done here):

1. Bump `ORCHESTRATOR_PIN_SHA` to a merged commit that contains this change.
2. On the step that runs `scripts/ci/contextual_orchestrator_review_launcher.py`
   (the sidecar step in `noema-review.yml`, and in `strix.yml` and
   `opencode-review-dispatch.yml` if they adopt it), add one step env value:
   `CONTEXTUAL_ORCHESTRATOR_OBSERVED_HEALTH_QUARANTINE: enabled`.
   Use a repository variable (for example
   `${{ vars.CO_OBSERVED_HEALTH_QUARANTINE || 'disabled' }}`) so the owner can
   roll back without a code change. The value is a non-secret toggle.
3. Verify in the uploaded sidecar log that the startup line reads
   `observed_health_quarantine enabled=True source=kv`. Then re-measure
   served p50/p90 and slow-failure seconds against this runbook's baseline
   before calling it an improvement.

No launcher Python change is needed.

## 429 study (analysis only; 429 behavior unchanged)

**Code, at this branch:**

- `_invoke` (`orchestrator.py` ~11137–11204) records the quota cooldown
  (`if exc.provider_status in (429, 503): self._record_rate_limit(...)`).
  It then classifies the error as
  `decision = classify_provider_transport_failure(exc.retryable)`. A 429 is
  `retryable=True`, and `tool_fallback.classify_provider_transport_failure`
  returns `circuit_failure=True` for every retryable failure (the
  `retryable` branch of `_decision(..., circuit_failure=True)`). So the
  breaker is charged at `if decision.circuit_failure: self._record_failure(...)`.
  The code comment there says "retry-classified failures always trip the
  circuit".
- `stream_route` (~7961) follows the same pattern
  (`classify_provider_transport_failure(upstream.retryable)` then
  `_record_failure`), so a pre-byte stream 429 is charged as well.
- The virtual passthrough loop in `proxy_completion` (~6587–6592) sets
  `skip_breaker = request_too_large or capability_mismatch or (rate_limit_signal is not None and rate_limit_signal[0] == 429)`.
  A 429 is recorded only as a quota cooldown.

**What pins each behavior:**

- Passthrough: `tests/test_rate_limit_aware_admission.py::test_429_does_not_trip_circuit_breaker_but_503_still_does`,
  and the constructor comment (~5793) stating that a 429 "must never trip or
  feed `_circuit`".
- `_invoke`: no test asserts that a provider 429 charges the breaker. The
  behavior follows only from `classify_provider_transport_failure`'s
  contract. It contradicts the constructor comment and the gateway rule that
  provider availability is transport evidence.
- `tests/test_orchestrator_dispatch_boundaries.py::test_invoke_retries_idempotent_rate_limits_with_circuit_and_backoff`
  concerns a *tool* rate limit, and it clears on success.

**Reproduction:** `tests/test_rate_limit_breaker_asymmetry.py` uses one
fixture. The first-ranked agent returns HTTP 429 with `Retry-After: 7` at
`ModelClient._open_provider`, and the second agent succeeds. The same pool
and messages go through `route_once` and through `proxy_completion`.

- Both paths record the quota cooldown.
- `route_once` leaves `_circuit["first_agent"]["failures"] == 1.0`.
- `proxy_completion` leaves `"first_agent" not in _circuit`.

**Replay quantification (101 artifacts):**

- Served 429 attempts that the deployed path charged to the breaker (a
  `circuit_failure` line follows): **144**. 12 more were not charged.
- Deployed log: **11 of 66** `circuit_opened` events (16.7 %) had a 429 in
  the charged streak since the last clear/reset.
- Legacy replay (flag off): 64 episodes, 11 with a 429 in the streak.
  Excluding 429 gives 53 episodes.
- Flag on: 37 episodes, 5 with a 429 in the streak. Excluding 429 gives 32
  episodes (`observed-health-quarantine-replay-exclude-429.json`).
- Estimated saved seconds: **36,831.6 s including 429 vs 36,827.5 s
  excluding it (Δ 4.1 s)**. False-positive episodes are 1 vs 1, and harmful
  removals 1 vs 1. Charged 429s are fast (p50 0.1 s), so skipping them saves
  almost nothing, while each one moves a member toward the open state.

**Arguments:**

- *For counting 429 as health:* a member that is persistently throttled is
  unavailable to this gateway, and a breaker trip moves traffic elsewhere
  sooner.
- *Against:*
  - 429 is account or quota capacity, not model correctness or endpoint
    health. It is often shared by sibling models on the same key, so charging
    one member mislabels the cause.
  - The gateway already has a dedicated, provider-stated quota mechanism
    (`_record_rate_limit`, `Retry-After`), and `_failover_candidates` already
    skips cooling-down members. A breaker trip adds a second, unrelated
    cooldown (30 s legacy; 30 s or more under the quarantine) on top of the
    provider's own.
  - AGENTS.md treats request-size 413 as never member health, and provider
    uptime as transport evidence rather than quality. The same reasoning
    keeps quota out of health.
  - The two chat paths disagree today, so the same provider response has
    different consequences depending on the request shape.

**Recommendation (not implemented):** make `_invoke` and `stream_route`
match the passthrough path. Keep recording the 429 quota cooldown, but do not
call `_record_failure` for a provider 429. Leave 503 as a real availability
signal, as the passthrough path does.

- Land it as its own PR with a RED on the fixture above, flipping the
  `route_once` assertion.
- Check `test_tool_execution_fallback` and `test_rate_limit_aware_admission`
  for storm-wait interactions.
- On this evidence the throughput effect is negligible (Δ 4.1 s over 101
  runs). The benefit is correctness and consistency, not speed.

## Owner decisions / open questions

1. Whether to set the switch in the review workflows. The default stays off
   under the 2026-09-07 boundary. The consumer handoff is above.
2. The 360 s cooldown is an experimental candidate. The corrected sweep
   shows 300–360 s dominating 600 s: slightly lower savings, but 1 harmful
   removal instead of 7. This is tuned on a biased sample.
3. Whether to adopt the 429 recommendation above in a separate PR.
4. A persisted health ledger across restarts is not implemented, so the
   gateway starts unquarantined.
5. With the flag off, the legacy judge pick still ignores the breaker. This
   is shown in the synthetic measurement (16 judge calls to an already-open
   member) and is left unchanged here.

## Reference

- J. Dean and L. A. Barroso, "The Tail at Scale," *Communications of the ACM*
  56(2), 2013, doi:10.1145/2408776.2408794 (already in `docs/papers/README.md`).
  It motivates keeping slow replicas off the critical path. It does not
  establish these weights or cooldowns, which rest only on the replay above.
