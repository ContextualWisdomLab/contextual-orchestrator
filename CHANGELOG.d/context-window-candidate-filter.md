Virtual-selector candidate selection (`proxy_completion`'s passthrough loop,
`route_once`, and `conduct`'s worker step) now skips a candidate whose known
`context_window` is provably smaller than a conservative lower bound on the
request's prompt tokens, instead of burning an attempt and relying on the
provider's own 400. The lower bound never overestimates: it uses the exact
native tokenizer when one is mapped for the candidate's model, otherwise a
documented character-count heuristic (`token_counting.estimate_lower_bound_tokens`)
that stays conservative across supported tokenizer families (ADR 0133). A
candidate with an unknown (`None`) window is never excluded. An explicitly
requested concrete model is never filtered. If every remaining candidate's
known window is too small, selection raises `ProviderRequestTooLargeError`
(413). When the filter excludes a candidate, the response's `orchestration`
extension gains `prompt_token_lower_bound`, `prompt_token_bound_source`, and
`context_window_excluded`.

Separately, a provider HTTP 400 context-window overflow
(`_is_context_length_exceeded_error`) is classified as a request-size
rejection inside `_is_request_too_large_error`, so it fails over without
penalizing provider/member health.
