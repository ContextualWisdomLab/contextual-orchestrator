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

Streamed route judging now inherits the request's image entitlement, and runtime
image admission excludes non-chat image-edit/video agents before any HTTP/SSE
success response or judge call.

The exact-head verification path now uses the supported `referencing` registry
instead of deprecated `jsonschema.RefResolver`, follows the renamed provider
embedding claim-lease constant, treats a null batch wait timeout as unbounded,
and closes every touched loopback listener after shutdown. Multimodal HTTP
fixtures declare image input explicitly instead of relying on a text-only mock.

Expanded warnings-as-errors verification now closes the remaining HTTP and
provider test listeners at their owning boundaries, including context-managed
provider threads, and makes the content-part casefold fixtures declare
`input:image`. This keeps the fail-closed capability contract while removing
test-owned socket leaks instead of suppressing `ResourceWarning`.

Endpoint preflight now normalizes accepted false forms of
`parallel_tool_calls` before request-shaped pool admission. A
`tool_call:single` vision endpoint therefore remains eligible for
`"false"` and `0` requests, while invalid forms still fail closed before
provider I/O.

Worker preflight now excludes agents whose operator policy lists `worker` in
`provider_exclusions`, so a role-ineligible vision-only pool returns HTTP 400
before streaming commits SSE. The related judge and Responses fixtures now
model an admitted text+image chat deployment and keep virtual passthrough in
the synthetic transport, preventing fixture defects from hiding owner failures.
