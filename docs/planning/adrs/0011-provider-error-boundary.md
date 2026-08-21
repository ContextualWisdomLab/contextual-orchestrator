# ADR 0011: Keep raw provider failures inside the gateway

- Status: Accepted
- Date: 2026-08-21

## Context

Provider HTTP bodies and exception messages can contain credentials, prompt
content, personal data, internal URLs, or vendor diagnostics. Retrying and
cross-provider failover must therefore not make a provider's raw exception
available through a public gateway error or an exception cause.

## Decision

1. Retry, passthrough, and Batch API transport failures expose only a
   package-owned message containing the affected agent and operation. Batch
   upload, polling, and output retrieval use the same boundary.
2. Model discovery reports a stable diagnostic code (`transport_error`,
   `timeout`, `http_status_<code>`, or `invalid_response`) without copying the
   provider response or exception text.
3. Exhausted failover raises the stable failover message without chaining the
   last provider exception.
4. Structurally invalid provider responses fail closed before cross-provider
   failover or circuit-breaker accounting; they are not transport failures.
5. Package-owned reasoning-only response guidance remains visible because it is
   deterministic local remediation, not provider output.
6. Provider diagnostics may be counted by allowlisted type/code in internal
   telemetry, but raw bodies, exception text, credentials, and prompts are not
   persisted or returned.
7. Direct SSE stream transport failures are converted to a package-owned
   streaming error without retry or failover. A stream may already have emitted
   bytes, so replaying it would duplicate output; the provider exception and
   response body remain inside the gateway.
8. Package-owned parse and identifier errors are raised outside provider-error
   handlers so neither `__cause__` nor implicit `__context__` exposes raw input.

## Consequences

Operators receive an actionable stable code and can use the agent/provider
identity to select the next diagnostic step. Exact vendor text is unavailable
at the public boundary; it must be inspected only in the provider's own
authorized observability system. This is intentional because gateway logs and
responses have a wider audience than provider credentials and request data.

## Verification

`tests/test_model_discovery.py`, `tests/test_provider_reliability.py`,
`tests/test_model_judge.py`, and `tests/test_batch_optimizer.py` assert that
provider response text is absent from public messages, causes, and contexts,
while the full suite must remain green before merge.

## References

MITRE. (n.d.). *CWE-209: Generation of error message containing sensitive
information*. https://cwe.mitre.org/data/definitions/209.html

OWASP Foundation. (2023). *Application Security Verification Standard 4.0.3*.
https://owasp.org/www-project-application-security-verification-standard/
