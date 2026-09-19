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
image requirement, and runtime image pools require both `input:text` and
`input:image` evidence so a mixed figure review cannot fall through to a
text-only or image-only model after initial selection.
