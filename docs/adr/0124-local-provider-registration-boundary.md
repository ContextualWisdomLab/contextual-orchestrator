# ADR 0124: Keep local providers out of HTTP agent registration

- Status: Accepted
- Date: 2026-08-22

## Context

Local `mlx://` and `local://` providers intentionally connect to a loopback
model runtime whose port is chosen by the operator. The HTTP agent-pool API
also accepted those URLs. Consequently, an actor holding the administrative
API credential could persist a worker that made the orchestrator connect to an
unrelated loopback service. Strix reported that path as server-side request
forgery (SSRF).

The transport already resolves every endpoint before use, rejects non-loopback
addresses for local providers, rejects non-public addresses for remote
providers, and connects to the validated address without a DNS relookup. Those
controls prevent remote-host and DNS-pinning escapes, but they do not establish
that an arbitrary loopback port is a model runtime.

## Decision

The HTTP agent-pool create endpoint rejects `mlx://` and `local://` provider
URLs before an agent can be persisted. Local providers remain available through
trusted process-startup configuration, where the operator controls the runtime
and port. HTTP-created remote providers retain the existing HTTPS, credential,
host-policy, public-address, and pinned-destination checks.

We do not use a generic loopback-port allowlist. A port number is not a service
identity, local model runtimes legitimately use configurable ports, and an
unrelated process could bind an otherwise allowed port. Separating trusted
bootstrap configuration from the remotely mutable control plane closes the
confused-deputy path with the smaller and stronger boundary.

## Consequences

- Buyers can still run MLX and other local models by declaring them at trusted
  startup.
- API clients receive a named `400` response directing them to startup
  configuration when they try to register a local provider.
- Even an authenticated admin request cannot turn the orchestrator into a
  loopback port scanner through dynamic agent creation.
- Existing mock agents and HTTPS provider registration remain unchanged.

## Standards and research grounding

OWASP recommends allowlisting identified trusted destinations and applying
defense in depth for SSRF. NIST zero-trust guidance requires least-privilege,
per-request access decisions instead of granting broad trust after
authentication. The selected boundary applies both principles without treating
an arbitrary local port as an identity.

## References

Open Worldwide Application Security Project. (n.d.). *Server-side request
forgery prevention cheat sheet*. OWASP Cheat Sheet Series. Retrieved August 22,
2026, from https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html

Rose, S., Borchert, O., Mitchell, S., & Connelly, S. (2020). *Zero trust
architecture* (NIST Special Publication 800-207). National Institute of
Standards and Technology. https://doi.org/10.6028/NIST.SP.800-207
