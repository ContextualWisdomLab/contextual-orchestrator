# Model-group endpoint race (issue #102)

## Contract

Agents with a non-empty multi-word snake_case `model_group` are treated as
operationally equivalent replicas. `_invoke` races those peers concurrently and
returns the first valid completion, using non-blocking executor shutdown so
slow losers do not reintroduce tail latency.

Ungrouped agents and distinct paper roles remain sequential failover so
thinker/worker/verifier/synthesizer diversity is preserved.

## Admin / API

- Create: `model_group` accepted on agent create keys.
- Patch: `model_group` accepted on agent patch keys.
- Admin payload includes `model_group`.

## Tests

`tests/test_provider_reliability.py` includes a timing test where a slow replica
does not delay the fast replica answer, and role-temperature propagation into
the race path.
