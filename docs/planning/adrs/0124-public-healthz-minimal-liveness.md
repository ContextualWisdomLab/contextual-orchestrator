# ADR 0124: Keep Public Health Liveness Minimal

- Status: Accepted
- Date: 2026-08-22

## Context

The unauthenticated `GET /healthz` endpoint is used by container and load
balancer probes. Its earlier response also exposed enabled and candidate agent
counts, batch backend names, provider-readiness state, and usage-record volume.
Those values reveal deployment topology and operational activity to an
unauthenticated caller and are not needed to establish process liveness.

## Decision

The public liveness response contains only `status` and `service`. Detailed
worker, provider, backend, and usage diagnostics remain behind the existing
authenticated administrative routes, including provider readiness.

## Consequences

- Probes retain a stable unauthenticated HTTP 200 contract.
- Operators must use an authenticated diagnostic route for readiness and
  topology evidence.
- Clients depending on the removed diagnostic fields must migrate to the
  authenticated administrative surfaces.

## Security basis

This implements the OWASP API Security Top 10 guidance to avoid exposing
unnecessary sensitive operational information through public API responses.

## References

OWASP Foundation. (2023). *OWASP API Security Top 10 2023*.
https://owasp.org/API-Security/editions/2023/en/0x11-t10/
