# Provider stream UTF-8 boundary

## Decision

Contextual Orchestrator treats provider server-sent-event bytes as untrusted network input. A real provider stream is accepted only when its response uses the `text/event-stream` media type, every consumed line stays within the existing cumulative response-byte budget, and each line is valid UTF-8 before any event-data interpretation occurs.

If one consumed SSE line is not valid UTF-8, orchestration fails closed with the stable public error `malformed provider stream event`. The original `UnicodeDecodeError` is deliberately suppressed so provider-controlled bytes, byte positions, or decoder diagnostics are not carried into ordinary exception text. The response and direct connection are still closed by the existing response context boundary.

This rule does not change provider routing, model selection, retry policy, credential resolution, DNS pinning, TLS identity, proxy rejection, redirect rejection, the 8 MiB response budget, or the OpenAI-compatible `[DONE]` terminal-marker contract.

## Why this is required

The WHATWG HTML Standard defines the server-sent-event stream format as `text/event-stream` and states that event streams are always decoded as UTF-8. RFC 8259 independently requires JSON exchanged between systems outside a closed ecosystem to use UTF-8. Because this runtime validates JSON-bearing `data:` frames from external model providers, malformed UTF-8 is protocol-invalid input rather than recoverable text.

Failing before JSON parsing also keeps the error boundary deterministic. Python's native `UnicodeDecodeError` may retain the offending byte sequence and byte offsets. Those diagnostics are useful inside a controlled parser test but are unnecessarily detailed at the provider trust boundary, where response content may be confidential, adversarial, or both.

## Verification

The regression was introduced test-first at commit `76fc98ba720632950df732cb38c1f58df4e42b0b`. The test supplies an `HTTPResponse`-shaped `text/event-stream` response containing malformed UTF-8 plus recognizable provider-controlled text and requires:

- a stable `RuntimeError` classification;
- no provider-controlled text in the public exception string;
- deterministic response cleanup; and
- deterministic connection cleanup.

The production repair at commit `e46a9d894a3951a991d177c879eb0b9247882cea` catches only `UnicodeDecodeError` at the UTF-8 decoding boundary and re-raises the existing malformed-stream error without exception chaining. All byte-budget, framing, media-type, JSON, and terminal-marker checks remain independently enforced.

Repository GitHub Checks on the final exact head remain authoritative. A predecessor-head or local diagnostic result does not authorize merge.

## Failure and rollback boundary

If a provider emits malformed UTF-8, operators should treat the response as a provider/protocol failure and inspect provider-side telemetry under the provider's own confidentiality controls. The orchestrator must not relax decoding to replacement characters or another character encoding because doing so would admit data outside the standardized SSE/JSON interoperability contract.

Rollback consists of reverting the production and regression commits together. Removing only the regression would weaken assurance; removing only the production guard would intentionally restore the demonstrated disclosure-prone exception path.

## Authority boundary

This control validates transport syntax only. It does not establish truthfulness, safety, authorization, model identity, provenance, semantic correctness, or successful completion of model output. Hosts and downstream services retain their existing authorization, tenancy, retention, audit, and model-use responsibilities.

## References

Bray, T. (Ed.). (2017). *The JavaScript Object Notation (JSON) Data Interchange Format* (RFC 8259). Internet Engineering Task Force. https://doi.org/10.17487/RFC8259

WHATWG. (2026, July 16). *HTML Standard: Server-sent events*. https://html.spec.whatwg.org/dev/server-sent-events.html
