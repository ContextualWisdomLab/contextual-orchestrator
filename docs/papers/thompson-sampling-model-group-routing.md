# Thompson sampling for model-group routing

Status: research traceability for `ModelGroupRouter.sampled_ranked_member_ids` on PR #1034.

## Decision boundary

Live serving uses posterior sampling to avoid deterministic winner-take-all selection after measured outcomes exist. Administrative and reporting reads remain deterministic. The implementation draws from each observed member's Beta posterior and combines that draw with the repository's measured latency term; it does not change the stored posterior or fabricate observations.

The cited literature supports the probability-matching / exploration-exploitation mechanism, but its guarantees must not be overstated. Thompson (1933) supplies the original posterior probability-matching construction. Chapelle and Li (2011) provide empirical evidence that Thompson sampling is a competitive baseline on simulated and real bandit data. Agrawal and Goyal (2012) prove logarithmic expected regret for stochastic Bernoulli multi-armed bandits under their analyzed Thompson-sampling setting.

`contextual-orchestrator` does **not** implement exactly the reward model in Agrawal and Goyal (2012): routing ranks a Beta stability sample divided by an EWMA latency estimate. Therefore the COLT regret bound is supporting evidence for posterior sampling of Bernoulli stability, not a proof of regret or optimality for the repository's composite successful-responses-per-second score. Any such claim requires a separate model and acceptance experiment.

## Code traceability

| Research concept | Repository implementation | Acceptance evidence |
|---|---|---|
| Posterior probability matching | `contextual_orchestrator/model_group.py::ModelGroupRouter.sampled_ranked_member_ids` | Seeded sampling tests in `tests/test_model_group.py` |
| Bernoulli success/failure posterior | `observe_success`, `observe_failure`, per-member `alpha` / `beta` | Existing model-group posterior/report tests |
| Deterministic reporting vs stochastic live selection | `ranked_member_ids` vs `sampled_ranked_member_ids`; `_measured_member_order(sample=...)` | Admin/report callers keep `sample=False`; serving refinement requests `sample=True` |
| Integer completed-outcome invariant under fractional prior refresh | `_outcome_count` shared by live observation-count and report paths | RED `c8223a3e4f10c2c48396359abdbad7520b84e920`; GREEN `40a5cc41e4e10525e6fdb73f4a7b19682a083e24` |

## Risks and follow-up acceptance

- The theory cited here does not validate the latency-normalized composite score. Measure routing regret / successful responses per second on right-cleared traffic or an approved replay before making an optimality claim.
- Members with no real outcomes currently retain the repository's neutral static score rather than receiving a sampled prior draw. This preserves the existing no-evidence ordering contract but is a repository-specific cold-start policy, not a consequence of the cited Thompson-sampling theory. A future change must test starvation and first-observation acquisition explicitly.
- Prior pseudo-counts may be fractional while completed outcomes are integral. Binary floating-point subtraction can drift below an integer; PR #1034 therefore recovers the domain-invariant completed-outcome count before deciding whether a member is observed.

PDFs are not vendored solely for this change because redistribution permission is not assumed. The primary publication pages below are the traceable sources.

## References

Agrawal, S., & Goyal, N. (2012). Analysis of Thompson sampling for the multi-armed bandit problem. In S. Mannor, N. Srebro, & R. C. Williamson (Eds.), *Proceedings of the 25th Annual Conference on Learning Theory* (Vol. 23, pp. 39.1–39.26). Proceedings of Machine Learning Research. https://proceedings.mlr.press/v23/agrawal12.html

Chapelle, O., & Li, L. (2011). An empirical evaluation of Thompson sampling. In J. Shawe-Taylor, R. Zemel, P. Bartlett, F. Pereira, & K. Q. Weinberger (Eds.), *Advances in Neural Information Processing Systems 24*. https://papers.nips.cc/paper/2011/hash/e53a0a2978c28872a4505bdb51db06dc-Abstract.html

Thompson, W. R. (1933). On the likelihood that one unknown probability exceeds another in view of the evidence of two samples. *Biometrika, 25*(3–4), 285–294. https://doi.org/10.1093/biomet/25.3-4.285
