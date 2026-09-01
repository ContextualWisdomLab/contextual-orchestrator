# ADR 0039: Request-scoped configured endpoint routing

- Status: Accepted
- Date: 2026-09-01

## Context

Chat Completions and Responses may route across agents discovered from several
configured provider endpoints. A caller can have an authorization or data
residency requirement to remain on one of those endpoints. A caller-supplied
URL must never become a transport destination or alter global discovery.

## Decision

The optional `routing.endpoint` field is accepted only by Chat Completions and
Responses. It selects an absolute HTTP(S) endpoint already present in the
enabled agent configuration; it is never used as a destination. Endpoint
identity canonicalizes scheme, host, default port, and path, treating one
terminal `/v1` as a transport suffix. Credentials, query strings, fragments,
and non-HTTP(S) schemes are rejected.

The matched agent identifiers form a request-local candidate set for planning,
worker, verifier, judge, synthesizer, retry, failover, proxy, and streaming
paths. Generated plans are checked against the same set, and routing caches are
partitioned by a non-reversible digest of the endpoint identity. The constraint
uses context-local state and never mutates the discovered agent pool.

An unmatched selector or a conflict with an explicit concrete model fails with
OpenAI-shaped HTTP 400 code `endpoint_unavailable`. Endpoint-bound work remains
synchronous because a deferred job cannot retain this request-local boundary.
The `routing` extension is removed before provider transport. Omitting the
field preserves automatic discovery and routing; unsupported surfaces continue
to reject the key.

## Consequences

Deployments can constrain one request without creating arbitrary outbound
request capability or losing provider discovery. Tests use synthetic endpoint
names; runtime endpoint selectors and credentials do not enter repository
artifacts.
