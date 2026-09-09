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

## Fractional-row follow-up

The initial correction preserved coercion behavior, but follow-up reproduction
at `4cc0bf2c` showed `0.7`, `1.7`, and `-0.7` silently stored as `0`, `1`, and
`0`. That contradicts the declared integer dichotomous-row contract. RED
`452d7490` produced 6 failed and 6 passed in 1.41s. Fix `89d8ed51` replaces
row-value `int` conversion with the already-imported `operator.index`: Python
and NumPy integers remain supported; fractions and numeric strings are rejected
before state mutation. The boolean accepted flag's existing conversion is
unchanged. Invalid persisted fractional/string rows now fail restoration rather
than fabricating observations; operators must repair their source evidence,
not round it or silently drop it. No valid integer-row migration is required.

At `89d8ed51`, 13 focused tests passed in 2.05s, including native integer
compatibility. Earlier 57-test local and 3595-test hosted receipts apply only
to `4cc0bf2c` and must not be carried forward to this changed code head.
