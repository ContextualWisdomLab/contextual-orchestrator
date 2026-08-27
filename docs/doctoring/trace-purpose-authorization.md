# Trace-purpose authorization

Trace-bearing responses are privileged data-access requests. Chat, admin
simulation, workflow/evaluation creation, and batch-result retrieval first
authenticate the caller, then require a separate verified `trace` purpose
scope before returning a trace. Owner-facing workflow/evaluation reads apply
the same gate when trace exposure is enabled. A denied purpose returns `401`
and no trace body.

Access reports always require the `trace` purpose because accessed outputs are
trace evidence. The authorization check runs before resource lookup, so a
caller without that purpose receives the same denial for owned and unknown run
identifiers.

`include_orchestration_trace` is a strict JSON boolean when present. Strings,
numbers, arrays, objects, and `null` are rejected; omission uses the explicit
server default. Validation runs before structured and tool request paths can
return.

The release gate records `orchestration_trace_access_granted` before the
response is released. The audit detail contains only route and purpose
metadata; prompts, outputs, credentials, and PII are not written to the event.

Production deployments should provide the scope-aware `bearer_verifier`; the
single static token mode remains a local-development escape hatch. Use the
existing admin workflow endpoints for operator trace inspection.

```bash
pytest -q tests/test_chat_include_orchestration_trace_http_honesty.py
```
