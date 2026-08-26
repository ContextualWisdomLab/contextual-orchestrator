# ADR 0005: Request-scoped provider deadline

**Status:** Accepted

## Context

An HTTP consumer can have a shorter patience budget than the sum of provider
retries and cross-provider failover. Reapplying a transport timeout to every
retry therefore permits an otherwise bounded workflow to outlive its caller.
The OpenAI-compatible JSON body is a provider contract and cannot carry
server-only scheduling controls. Structured-output, tool, Responses API, and
model-judge paths use raw passthrough and require the same deadline boundary.

## Decision

The caller may send `X-Request-Timeout-Ms` as a positive integer duration. The
server immediately converts it to a process-local monotonic deadline and never
forwards the header or a corresponding field to a provider. Every orchestration
attempt reads the same deadline. A provider receives the lesser of the remaining
request duration and the configured provider timeout; all transport retries for
that provider share that single budget. Backoff consumes the same budget. This
applies to decoded chat, full structured JSON, and binary provider responses.

An explicitly requested provider model retains exact `response_format`
passthrough and is never substituted. A virtual orchestrator model with
`json_schema` instead translates the schema into a multi-agent conduct request,
validates the synthesis locally with Draft 2020-12, and, when necessary, asks
admitted agents to repair the synthesis through ordinary chat. It never depends
on a provider-native structured-output surface. Every synthesis and repair call
shares the caller deadline, session, request-scoped failed-candidate set, trace,
and cost lineage. Each repair candidate is called at most once. If no admitted
candidate produces schema-valid JSON, the server returns typed
`no_viable_agent` with `Retry-After` instead of returning invalid JSON or an
opaque 500.

Structured readiness uses the same conduct, local validation, and ordinary-chat
repair path with a minimal valid Draft 2020-12 schema. A provider that lacks a
native schema parameter can therefore remain ready; a provider that cannot
complete the orchestrated repair cannot. Unsupported schema keywords fail
closed as `invalid_response_format` before any model call.

The deadline does not allocate a fraction to a provider, change model order,
change reasoning effort, or modify cost attribution. Successful failover retains
the serving provider's reported usage. Exhaustion fails closed as HTTP 504 with
`request_deadline_exceeded`. Absence of the header preserves the configured
provider timeout while still making it one budget across retries.

## Consequences

- A 180-second request can spend at most 90 seconds on a provider configured
  with a 90-second timeout and offer only the actual remainder to successors.
- Multi-agent workflow, structured validation, session, trace, and cost lineage
  remain unchanged.
- JSON-schema orchestration preserves the public OpenAI completion shape and
  never admits an unprobed catalog entry.
- An in-flight blocking provider transport can only be interrupted at the
  transport timeout boundary; cancellation below that boundary is provider and
  operating-system dependent.

## Security, operability, testing, and rollback

The control is an authenticated-request header parsed before orchestration. It
accepts only positive ASCII decimal integers representable as finite seconds.
Logs and provider bodies contain neither the deadline nor caller content. Tests
cover the shared retry budget, primary exhaustion followed by backup success,
total exhaustion, malformed headers, and usage preservation. Rollback removes
the header contract and deadline propagation together; retaining only one side
would recreate unbounded latency.

## References

Fielding, R., Nottingham, M., & Reschke, J. (2022). *HTTP semantics* (RFC
9110). Internet Engineering Task Force. https://www.rfc-editor.org/rfc/rfc9110

National Institute of Standards and Technology. (2020). *Security and privacy
controls for information systems and organizations* (NIST SP 800-53 Rev. 5).
https://doi.org/10.6028/NIST.SP.800-53r5
