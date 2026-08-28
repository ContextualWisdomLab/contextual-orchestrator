---
id: "0026"
title: "Require a separate trace purpose for trace-bearing responses"
status: accepted
proposed_date: "2026-08-20"
accepted_date: "2026-08-20"
deciders:
  - "repository maintainer"
affected_components:
  - "contextual_orchestrator/server.py"
  - "tests/test_chat_include_orchestration_trace_http_honesty.py"
---

# Require a separate trace purpose for trace-bearing responses

## Decision

Inference or admin authentication alone does not authorize a trace-bearing
response. Chat, admin simulation, workflow/evaluation creation, batch-result
retrieval, and trace-enabled workflow/evaluation reads require the verified
`trace` purpose scope. The server records a metadata-only audit event before
releasing the response and never trusts a caller-supplied purpose header.

Chat validates the trace flag before selecting structured, tool, streaming, or
ordinary execution, so no early-return path can weaken the request contract.
Access reports always require the trace purpose because their accessed-output
lists are trace evidence even when general trace exposure is disabled.

When `include_orchestration_trace` is present it must be a JSON boolean;
`null`, strings, numbers, arrays, and objects are rejected. Omission follows
the explicit server default.

The injected `bearer_verifier(token, scope)` is the production boundary for
OIDC/Keyverse claims. Static single-token mode permits the local development
escape hatch only. The CLI `--production` gate requires split static
admin/inference credentials (or a deployment-specific external verifier), so a
legacy single token cannot silently become a production trace credential; split
static admin/inference mode otherwise fails closed for the trace purpose because
it has no verified trace claim.

## Acceptance evidence

- an inference-only principal receives `401` for a trace request on each
  trace-bearing surface;
- a principal verified for both `inference` and `trace` receives the permitted trace;
- batch results and admin/workflow/evaluation trace paths use the same gate;
- malformed trace flags fail with `400` before orchestration;
- the audit event is written before the trace response path proceeds and
  contains no prompt, output, credential, or PII value;
- audit failure returns a generic `503` instead of releasing the trace.

Issue #117 remains open: batch jobs need their protected-main integration, and
the authorization adapter still needs tenant/resource/lifetime context. The
legacy single-token production migration is now guarded in the CLI and
canonical Compose path; its explicit local escape hatch remains documented.

## Research grounding

Yang, N., Barringer, H., & Zhang, N. (2007). A purpose-based access control
model. In *Proceedings of the 3rd International Symposium on Information
Assurance and Security (IAS 2007)*. IEEE. https://doi.org/10.1109/IAS.2007.29

The purpose-based model supports treating trace access as a separate policy
input rather than granting it implicitly from the inference role.
