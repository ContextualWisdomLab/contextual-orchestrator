# ADR 0038: Request-scoped configured endpoint routing

- Status: Accepted
- Date: 2026-08-28

## Context

The OpenAI-compatible Chat Completions and Responses surfaces may serve agents
from more than one configured provider endpoint. A caller sometimes has an
authorization or data-residency requirement to use one already-configured
endpoint. A caller-supplied URL must never become a transport destination, and
an endpoint constraint must not leak into another concurrent request.

## Decision

The optional `routing.endpoint` field is accepted only by Chat Completions and
Responses. It is an absolute HTTP(S) selector for an endpoint already present
in the enabled agent configuration; it is never used as a destination. Endpoint
identity canonicalizes scheme, host, default port, and path, treating one
terminal `/v1` as a transport suffix. Credentials, query strings, fragments,
and non-HTTP(S) schemes are rejected.

The exact matched agent identifiers form a request-local candidate set for all
planning, worker, verifier, judge, synthesizer, structured-repair, retry,
failover, proxy, and streaming paths. Generated plans are validated against the
same set. Routing and triage caches are partitioned by that set. The constraint
uses context-local state and never mutates the configured agent pool.

An unmatched selector or a conflict with an explicit concrete model fails with
the OpenAI-shaped HTTP 400 code `endpoint_unavailable`. The `routing` extension
is removed before provider transport. Omitting the field preserves automatic
model discovery and routing. Text Completions, embeddings, embedding batches,
and other surfaces retain their prior routing contract and reject the new key.

## Consequences

Deployments may select a configured endpoint without exposing provider
credentials or creating arbitrary outbound-request capability. Every role in a
multi-agent workflow remains within one endpoint boundary, while independent
requests and caches remain isolated. Tests use synthetic endpoint names; real
endpoint selectors remain runtime configuration and must not enter source,
documentation, fixtures, or logs.
