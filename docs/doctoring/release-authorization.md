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
- complete human, CodeRabbit, GitHub Advanced Security, Dependabot, OpenCode,
  Noema, and Strix finding inventory with zero unresolved findings.

The public result contains blocker codes and evidence counts only. It never
returns tokens, prompts, reviewer credentials, or private reasoning. A missing
snapshot produces `authority_evidence_unavailable`, so
`/api/v1/commercial_release_candidates/latest` remains useful for local product
demonstrations without claiming release authorization.

## Customer next action

Run the protected CI collector against the exact candidate SHA, attach its
machine-readable snapshot to the release review, then re-query the endpoint.
The release status can change only after that fresh evidence passes every gate.

## References

National Institute of Standards and Technology. (2023). *Artificial
intelligence risk management framework (AI RMF 1.0)* (NIST AI 100-1).
https://doi.org/10.6028/NIST.AI.100-1

GitHub. (n.d.). *About protected branches*. Retrieved August 20, 2026, from
https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches
