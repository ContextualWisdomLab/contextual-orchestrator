# Mixed quota retry regression contract

Observed 2026-09-27. Clean protected-main revision `aaa4dfdd9d3744f303436ae23e67cf0e06536347` fails `test_invoke_reraises_mixed_failure_without_waiting`: its assertion expects the pre-recovery non-quota error, while current routing deliberately retries only the quota-rejected candidate and eventually reports quota budget exhaustion. The unchanged baseline test fails after 167.93 seconds. This is inherited by PR #1249, not caused by its lifecycle repair.

The behavior originates in `d90a8f8e5` and its current integration `b1b2bc2d0`, merged through [PR #1222](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/1222). The repair preserves production policy. The updated regression advances its fake clock during simulated sleeps, isolates admission retries with an explicit zero tool-retry budget, and proves that the non-quota candidate is called exactly once, the rejected candidate is retried, the quota failure carries honest assumed-cooldown provenance, and quota rejection never trips its health circuit. No scanner or required check changes.

```sh
python -m pytest tests/test_provider_error_taxonomy.py -q
```

The module passes 28 tests on the updated baseline. Full hosted checks and independent review remain required.
