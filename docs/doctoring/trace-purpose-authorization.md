# Trace-purpose authorization

`include_orchestration_trace: true` is a privileged data-access request. The
chat endpoint first authenticates the inference caller, then requires a
separate verified `trace` purpose scope before returning the trace. A denied
purpose returns `401` and no trace body.

The release gate records `orchestration_trace_access_granted` before the
response is released. The audit detail contains only route and purpose
metadata; prompts, outputs, credentials, and PII are not written to the event.

Production deployments should provide the scope-aware `bearer_verifier`; the
single static token mode remains a local-development escape hatch. Use the
existing admin workflow endpoints for operator trace inspection.

```bash
pytest -q tests/test_chat_include_orchestration_trace_http_honesty.py
```
