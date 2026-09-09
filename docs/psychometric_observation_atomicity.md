# Rejected observation atomicity

Status: proposed correction on the PR #1067 owner stack, not released.

At base `84a6052369a7bf8b6faae5db475bb68a5ad54a91`,
`PsychometricRoutingEvidence.observe_context_id` changed retained vectors and
context order before validating the dichotomous row. An invalid replacement
therefore changed the embedding associated with an old response; an invalid new
context remained retained without incrementing the observation revision. This
could alter neighbor selection while the fitted response cache stayed unchanged.
Both normal `observe` and durable-state restoration reach this shared method.

RED commit `b335bfa7` reproduced both cases: 2 failed in 12.11s. Fix commit
`5a4c0e66` computes the copied vector, normalized vector, and validated response
tuple before changing retained state, under the existing lock. The same checks
then passed: 2 passed in 10.84s. No estimator, score weight, input-coercion policy,
runtime dependency, or production routing default changed. This is CO state
integrity, not a replacement for the fast-mlsirm numerical owner.

Reproduce from this checkout using the project's installed test environment:

```sh
python -m pytest tests/test_psychometric_observation_atomicity.py -q
```

Acceptance measured here: rejected new and replacement observations preserve
records, context order, normalized vectors, and observation revision (2/2).
This unit evidence does not establish customer accuracy or decision-latency
improvement, complete memory-allocation failure safety, or durable-store repair.
Independent review, full regression verification, protected merge, and release
remain required.
