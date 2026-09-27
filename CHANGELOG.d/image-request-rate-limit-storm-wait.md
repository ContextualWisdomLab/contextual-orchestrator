### Image-bearing requests wait out a rate-limit storm like text requests

- `_invoke` runs an image request on the text candidates when no candidate for a step is vision-capable. `_invoke_with_rate_limit_recovery` recomputed only the vision-required set, found it empty, and re-raised the 429 at once. A figure-bearing conduct review therefore failed immediately on a text-pool 429 storm, while the same storm on a text request was waited out.
- The storm-wait admission now applies the same no-vision fallback that `_invoke` uses, so it judges the storm on the candidates actually called. The wait budget, the pinned-model fail-fast, Retry-After handling and breaker accounting are unchanged.
- Regression: `tests/test_image_request_rate_limit_storm_wait.py` checks per-candidate call timing with and without `Retry-After`, plus an exhausted wait budget.
