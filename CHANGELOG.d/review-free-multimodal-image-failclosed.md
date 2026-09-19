Fixed `orchestrator/free` figure-bearing review so image_url parts require
discovery `input:image` (or legacy `vision`) free agents, admit free
text+image chat rows into the review sidecar pool, and fail closed with a
typed 400 when no image-capable free candidate remains — never a 200 that
silently ignores DOCX/HWPX figures (issue #1202). Image free admission now
composes the existing #940 `tool_call:single` request-shaped exclusion
instead of replacing general-free tool-call gating.

The follow-up repair carries the same `input:image` requirement through
single-agent Responses conversion, template planning, every conducted role,
and model-judge selection. Discovery capability/modality evidence is now
case-normalized before routing, the changed admission predicate is published
as review-readiness contract v2, and the review request ceiling is pinned by
test to the documented 32 MiB owner contract.

Direct-route judging and proxy replica/failover ranking now retain the same
image requirement. Runtime image pools reject explicit `input:image`-only
evidence, require `input:text` when any `input:*` evidence is present, and
retain the documented legacy `vision` admission when no `input:*` tags exist;
a mixed figure review therefore cannot fall through to a text-only or
explicitly image-only model after initial selection.

Endpoint-constrained free requests now apply the same request-aware image
predicate during endpoint preflight and pool admission. Chat Completions and
Responses therefore admit an endpoint-local free text+image agent, while a
text-only request still cannot treat that vision deployment as the blind free
pool and an endpoint without eligible local capacity still fails closed.
Chat image aliases are normalized before admission, disabled agents cannot
prove capacity, and an empty request-aware image pool returns HTTP 400 before
either streaming surface commits SSE headers.
