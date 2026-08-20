---
id: "0013"
title: "Require a separate trace purpose for trace-bearing chat responses"
status: accepted
proposed_date: "2026-08-20"
accepted_date: "2026-08-20"
deciders:
  - "repository maintainer"
affected_components:
  - "contextual_orchestrator/server.py"
  - "tests/test_chat_include_orchestration_trace_http_honesty.py"
---

# Require a separate trace purpose for trace-bearing chat responses

## Decision

Inference authentication alone does not authorize a trace-bearing response.
When a chat caller requests `include_orchestration_trace`, the server requires
the verified `trace` purpose scope and records a metadata-only audit event
before releasing the response. The server never trusts a caller-supplied
purpose header.

The injected `bearer_verifier(token, scope)` is the production boundary for
OIDC/Keyverse claims. Static single-token mode permits the local development
escape hatch; split static admin/inference mode fails closed for the trace
purpose because it has no verified trace claim.

## Acceptance evidence

- an inference-only principal receives `401` for a trace request;
- a principal verified for both `inference` and `trace` receives the trace;
- the audit event is written before the trace response path proceeds and
  contains no prompt, output, credential, or PII value;
- audit failure returns a generic `503` instead of releasing the trace.

## Research grounding

Yang, N., Barringer, H., & Zhang, N. (2007). A purpose-based access control
model. In *Proceedings of the 3rd International Symposium on Information
Assurance and Security (IAS 2007)*. IEEE. https://doi.org/10.1109/IAS.2007.29

The purpose-based model supports treating trace access as a separate policy
input rather than granting it implicitly from the inference role.
