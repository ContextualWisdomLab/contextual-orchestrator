# Release authorization evidence

The gateway exposes local product evidence, but it does not invent GitHub
protected-branch authority. `evaluate_release_authorization()` accepts only a
fresh read-only authority snapshot collected by the trusted CI governance path.

The evaluator fails closed when any of these is absent or inconsistent:

- repository and protected `main` identity;
- current contributor head equal to the protected head;
- verified ruleset and non-synthetic merge evidence;
- every required check completed successfully on the exact head;
- qualifying independent approval on the exact head;
- when an active ruleset requires last-push approval, the qualifying reviewer
  is not the principal who pushed the last contributor commit;
- a positive independent-approval requirement; a missing or zero-review policy
  is invalid and remains blocked;
- complete human, CodeRabbit, GitHub Advanced Security, Dependabot, OpenCode,
  Noema, and Strix finding inventory with zero unresolved findings.

The public result contains blocker codes and evidence counts only. It never
returns tokens, prompts, reviewer credentials, or private reasoning. A missing
snapshot produces `authority_evidence_unavailable`, so
`/api/v1/commercial_release_candidates/latest` remains useful for local product
demonstrations without claiming release authorization.

The release candidate, gap, procurement, contract, onboarding, operations,
security-attestation, value, close, go-to-market, launch, and completion report
chain receives the same verified snapshot. Nested release status therefore
cannot silently fall back to unavailable evidence after server verification.

## Customer next action

Register `CONTEXTUAL_ORCHESTRATOR_RELEASE_AUTHORITY_SIGNING_KEY` in the KV for
both the protected CI collector and the gateway. Run the collector against the
exact candidate SHA and persist its signed machine-readable output under
`artifacts/release-authority/<sha>.json`. Start the gateway with
`--release-authority-json` pointing at that file, then
re-query the admin endpoint. The release status can change only after that
fresh evidence passes every gate; restart with a newly collected file after
the candidate head changes.

```bash
mkdir -p artifacts/release-authority
python scripts/ci/release_authority_snapshot.py \
  --repo ContextualWisdomLab/contextual-orchestrator \
  --pr <number> \
  --expected-head-sha <sha> \
  --required-check Tests \
  --required-check Security \
  --findings-json <path> > artifacts/release-authority/<sha>.json
python -m contextual_orchestrator --serve \
  --release-authority-json artifacts/release-authority/<sha>.json
```

## References

National Institute of Standards and Technology. (2023). *Artificial
intelligence risk management framework (AI RMF 1.0)* (NIST AI 100-1).
https://doi.org/10.6028/NIST.AI.100-1

GitHub. (n.d.). *About protected branches*. Retrieved August 20, 2026, from
https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches
