---
title: "Provider-diverse discovery and cost-honest failover routing"
status: "implemented"
date: "2026-08-21"
scope: "PR #770"
---

# Provider-diverse discovery and cost-honest failover routing

## Decision

PR #770 makes model discovery fail closed for invalid catalog rows (a price
that is negative, non-finite, or a nonzero value that underflows to zero),
retains eligible candidates that simply have no reported price as an
explicit unknown-cost fallback, and selects a provider-diverse bootstrap
pool before ordinary chat routing. The selector is deterministic eligibility
and cost accounting; it is not a learned answer-quality judge and does not
claim to reproduce the learning systems in the cited work.

Virtual-model passthrough requests use that same provider-diverse pool for
tools, structured output, and Responses payloads. Each candidate receives one
attempt: RFC 9110 section 9.2.2 does not permit blind automatic replay of a
non-idempotent request, so ambiguous timeout and connection outcomes fail
closed. A rejected 429/5xx, stale 404/410 candidate, or temporary pre-request
DNS failure can advance without changing an explicitly requested concrete model.

## PR #1004 mixed-failure classification follow-up

Proposed on 2026-09-05, separate from the implemented #770 baseline above.
At head `2a6b41562114530315bb44d1aa3dede820a68da1`, structured synthesis
remembered retryable provider failures and missing-model errors separately,
then preferred the latter on exhaustion. A `502 → 404` or `404 → 502` sequence
therefore returned a non-retryable 404 despite a transient failure being known.
The first correction changed only the shared exhaustion order: return the
recorded retryable upstream error before the missing-model error. It retained
an existing post-404 endpoint restriction, which the subsequent contract audit
below found was not justified for an unpinned virtual request.

The two mixed-order cases in `tests/test_structured_output_distinct_fallback.py`
failed with `404 != 502` before the first correction. That version asserted two
endpoint-local calls and a retryable 502, but incorrectly forbade the still
eligible alternate endpoint. The current tests require that attempt too before
reporting exhaustion.
The paired cases in `tests/test_chat_response_format_http_honesty.py` also
exercise the real HTTP handler and require HTTP 502 with `api_error` and
`retryable=true`; both returned HTTP 404 on an isolated pre-fix checkout.
Run with `uv run pytest -q tests/test_structured_output_distinct_fallback.py tests/test_chat_response_format_http_honesty.py`.
These are local regression results, not protected-main or live-provider proof.

### Per-attempt observations after the classification fix

At `cdb672c23a23dd3c83be3cd4190f5a7b1d5da032`, the full local suite passed
(`3409 passed, 2 skipped in 657.92s`), but independent review then found that
the inner synthesis loop recorded circuit failures while the outer exception
handler recorded only the final model-group failure. Successful fallback lost
the first group failure entirely. Its request-wide recorded flag also hid a
later terminal 400 or malformed-output budget stop from the circuit counter.

The local correction updates both existing ledgers in a synthesis-only helper,
at the actual failed candidate. It does not alter the global circuit helper:
other callers already own their group updates and would double count. The
outer handler records only an otherwise unrecorded failure. Do not reset the
flag for every candidate: after `502 → 413`, exhaustion returns the first
candidate's retryable error, which must not become a failure of the 413 model.
Malformed output is recorded before budget enforcement, without allowing
another call or dropping incurred usage. Repair accounting is unchanged.

Run `uv run pytest -q tests/test_structured_output_distinct_fallback.py tests/test_structured_output_malformed_synthesis_usage.py`.
The real circuit/group assertions produced `7 failed, 11 passed` before the
fix and `18 passed` afterward. They cover `502 → success`, both 502/404 orders,
an immediate 400, `502 → 400`, `502 → 413`, and billed malformed output with
and without a prior same-endpoint 502. The budget-stop cases preserve usage
and prohibit the next provider call. Broader provider taxonomy, group, effort,
and actual HTTP-handler regressions passed 124 tests; this is not hosted or
live-provider acceptance evidence.

Independent review then reproduced a client exception before any response
object was returned. After a prior 502 this raised `UnboundLocalError`; after
a prior malformed object it copied that object's usage into the next attempt.
Both cases failed on `18a29d144a4e2c14e607bfe7886fd486ba469190`. This is a
supported client-boundary reproduction, not a claim that the ordinary HTTP
transport emitted a particular Content-Length failure. Reset the response
per candidate and read usage only from a returned mapping. The new tests in
`tests/test_structured_output_malformed_synthesis_usage.py` require one failure
per rejected candidate, preservation of reported usage, no usage copied to the
response-less attempt, and unavailable total usage rather than a false zero.
All 178 focused budget/provider/group/effort/HTTP tests passed after that fix.
The full run on `18a29d14` was explicitly interrupted after this finding
(`exit 2`, `1199 passed in 299.44s`); it is not passing full-suite evidence.

### Stale models must not introduce an implicit endpoint pin

CodeRabbit's [current-head finding](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/1004#discussion_r3939972170)
identified an eligible alternate endpoint skipped after a 404. The initial
rejection confused existing behavior with a requirement. Issue #998 and ADR
0035 protect caller-selected endpoints, not an endpoint inferred from a failed
candidate. The original guard in `99c05a0f58972c7d1b9e19a3e0f9ef7b4cf113af`
was tested only with a successful same-endpoint sibling; it did not establish
that other endpoints must remain forbidden after all local candidates fail.

Against `69b79a6bc2a6039396d6fd03edcac5bef80c686e`, the expanded unit/HTTP
suite produced `12 failed, 37 passed`. Recovery now reuses the complete
already-filtered candidate list without endpoint narrowing or provider-name
deduplication. A candidate excluded during evidence collection can advance
to another eligible endpoint. Malformed responses on later endpoints use the
same incurred-usage and budget checks as the initial endpoint. Concrete model,
explicit endpoint, free/ZDR, file-replica, effort, and failure-classifier
boundaries remain intact; JSON repair remains bound to its original candidate.

The two regression files plus `tests/test_structured_output_malformed_synthesis_usage.py`
pass all 52 tests after this correction. They exercise both AUTO and FREE,
mixed and all-stale failures, later-provider model siblings, explicit endpoint
rejection, pre-excluded initial candidates, and a later-endpoint malformed
response that must stop before exceeding the budget. Full-suite, hosted, and
protected-main receipts remain separate evidence.

Independent source review at `2582176d92662b2797af4ed072aa7e71883d6982`
then found two sibling-path failures. All malformed responses, including mixed
malformed/413 orders, exhausted into a size-limit error even when no provider
reported 413. A repair rejected by the client before return bypassed the
returned-malformed-response handler, losing the synthesis usage and failed-run
record. Eight new cases failed (`8 failed, 3 passed`). The shared exhaustion
path now retains a malformed-response failure before considering size-only
exhaustion, and both pre-return and returned malformed repairs share one
handler. Repair response state starts empty, preserving known synthesis usage
without copying it into the unavailable repair usage. All 60 focused tests
pass. The full run at `2582176d` was explicitly interrupted after this finding
(`exit 2`, `568 passed in 153.54s`); it is not full-suite passing evidence.

## Research-to-code mapping

| Implementation boundary | Evidence-informed reason | Acceptance evidence |
| --- | --- | --- |
| Reject malformed, negative, or non-finite price rows | A cost-aware router must not treat missing or invalid evidence as zero cost. | Discovery and persisted-price tests reject the row before selection. |
| Keep unknown-price candidates only as an explicit fallback | Cost optimization must remain honest when price evidence is incomplete. | Selection tests never rank an unknown price above a valid priced candidate. |
| Prefer distinct providers in the bootstrap pool | A gateway needs an upstream failover set rather than several aliases for one provider. | Provider-diversity tests assert the configured pool spans available providers. |
| Fail over virtual-model passthrough once per provider | Preserve raw provider features without retry amplification; concrete model selection remains a caller contract. | Passthrough tests cover 404, 410, 429, 503, wrapped failures, caller errors, and exhaustion. |
| Leave quality judgment to evaluation/review policy | Routing signals and answer-quality judgment have different failure modes. | Existing model-judge and fail-closed routing tests remain the quality boundary. |

The routing papers and OA PDFs are already committed in the prerequisite
stack base under `docs/papers/` (`routellm-routing-2406.18665.pdf`,
`hybrid-llm-query-routing-2404.14618.pdf`, and
`frugalgpt-cost-2305.05176.pdf`). This doctoring record makes their relevance
to the exact discovery selector explicit instead of treating inherited files
as incidental documentation.

## APA 7 references

Chen, L., Zaharia, M., & Zou, J. (2023). *FrugalGPT: How to use large
language models while reducing cost and improving performance*. arXiv.
https://arxiv.org/abs/2305.05176

Ding, D., Mallick, A., Wang, C., Sim, R., Mukherjee, S., Rühle, V.,
Lakshmanan, L. V. S., & Awadallah, A. H. (2024). *Hybrid LLM:
Cost-efficient and quality-aware query routing*. International Conference on
Learning Representations. https://arxiv.org/abs/2404.14618

Ong, I., Almahairi, A., Wu, V., Chiang, W.-L., Wu, T., Gonzalez, J. E.,
Kadous, M. W., & Stoica, I. (2024). *RouteLLM: Learning to route LLMs with
preference data*. arXiv. https://arxiv.org/abs/2406.18665

Fielding, R., Nottingham, M., & Reschke, J. (2022). *HTTP semantics* (RFC
9110). Internet Engineering Task Force. https://www.rfc-editor.org/rfc/rfc9110
