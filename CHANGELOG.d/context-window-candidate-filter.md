# Context-window candidate filter

Virtual-selector candidate selection (`proxy_completion`'s passthrough loop,
`route_once`, and `conduct`'s worker step) now skips a candidate whose known
`context_window` is provably smaller than a conservative lower bound on the
request's prompt tokens, instead of burning an attempt and relying on the
provider's own 400 (see PR #1174, `fix/context-length-exceeded-failover-20260913`,
for the complementary all-providers-413-after-the-fact lane). The lower bound
never overestimates: it uses the exact native tokenizer when one is mapped for
the candidate's model, otherwise a documented character-count heuristic
(`token_counting.estimate_lower_bound_tokens`) that stays conservative across
every supported tokenizer family. A candidate with an unknown (`None`) window
is never excluded -- absence of evidence is not evidence of a too-small
window. An explicitly requested concrete model is never filtered; the
provider's own error remains the honest answer for a caller's own choice. If
every remaining candidate's known window is too small, selection raises the
existing `ProviderRequestTooLargeError` (413) naming the smallest known
window and the lower-bound count, instead of an empty pool or a 500. When the
filter excludes a candidate, the response's `orchestration` extension gains
`prompt_token_lower_bound`, `prompt_token_bound_source`
(`"exact"`/`"estimate_lower_bound"`), and `context_window_excluded`.
