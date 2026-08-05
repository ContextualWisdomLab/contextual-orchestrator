# Hourly NVIDIA NIM broker egress boundary

## Decision

The scheduled product-development agent reaches NVIDIA NIM only through the repository-owned credential broker. The broker accepts a fixed local operation allowlist, resolves the fixed upstream hostname once per accepted request, validates the complete A and AAAA answer set, and then connects only to the validated globally routable addresses from that snapshot.

The connection retains `integrate.api.nvidia.com` as the HTTP authority, TLS Server Name Indication value, and certificate-verification identity. It does not reconnect by hostname after validation. Redirects are rejected, caller authorization and forwarding headers are discarded, ambient HTTP proxy configuration is not consulted, and the NVIDIA credential is added only to the fixed-origin upstream request.

This boundary is fail closed:

- an empty DNS answer set is rejected;
- any non-global answer rejects the complete answer set rather than selecting a convenient public sibling;
- duplicate addresses are removed deterministically in resolver order;
- more than eight distinct addresses are rejected to bound retries and credential-bearing connection attempts;
- transport failure may advance only to another address in the same validated snapshot;
- resolver, socket, TLS, and HTTP failures return one generic broker error without diagnostic or credential detail;
- every attempted connection and failed TLS socket is closed deterministically.

## Why hostname validation alone is insufficient

A fixed allowlisted hostname prevents caller-selected destinations but does not by itself bind validation to connection. A conventional hostname-based HTTPS client can perform another DNS lookup when it opens the socket. If the answer changes between policy validation and connection, the credential-bearing request can reach an address that was never approved.

OWASP's SSRF guidance identifies this DNS-pinning or rebinding class and recommends retrieving all A and AAAA answers, applying public-address validation to each answer, and disabling redirection. The implementation therefore treats the resolver output as connection evidence, not merely as a preliminary hostname check.

## Address-classification contract

Python's `ipaddress.ip_address(...).is_global` is the executable classification boundary. The Python documentation defines it in terms of the IANA IPv4 and IPv6 special-purpose registries and explicitly notes that shared address space `100.64.0.0/10` is not global. This avoids relying on `is_private` alone and covers loopback, link-local, documentation, shared, multicast, unspecified, reserved, and other non-globally-reachable destinations through one conservative predicate.

RFC 6890 defines the common information model for the IANA IPv4 and IPv6 Special-Purpose Address Registries, including whether a block is globally reachable. The runtime classification and regression fixtures are maintained against that registry-derived semantic rather than a repository-local CIDR list.

## Verification evidence

Permanent tests cover:

- globally routable IPv4 and IPv6 answer retention and deterministic deduplication;
- empty, private, mixed public/private, malformed, and excessive answer rejection;
- no TLS construction after a non-global or malformed DNS result;
- retry only across the once-validated address snapshot;
- original-host HTTP authority, TLS hostname, and credential injection on every approved attempt;
- direct socket dialing of the pinned IP;
- cleanup of every failed connection and raw socket when TLS setup fails;
- generic, secret-free broker errors;
- unchanged request, concurrency, body, response, redirect, and media-type budgets.

The injected `connection_factory` remains a network-free test seam. Production construction leaves it unset and cannot skip DNS validation or pinning.

## Residual risks and operational controls

DNS pinning prevents hostname re-resolution from changing the destination after validation, but it does not replace DNSSEC, certificate transparency, secure runner networking, or upstream account controls. A globally routable malicious address can still be returned by a compromised resolver; TLS hostname and certificate verification remain mandatory to prevent that address from impersonating NVIDIA. The broker container therefore uses the platform trust store, keeps hostname checking enabled, has no repository or GitHub-token mount, and exposes only the private Docker-network listener to the isolated agent.

The address snapshot is intentionally per accepted broker request rather than process-long. This preserves normal provider address rotation while ensuring that every credential-bearing connection is bound to the exact evidence evaluated for that request.

## References

Cotton, M., Vegoda, L., Bonica, R., & Haberman, B. (2013). *Special-purpose IP address registries* (RFC 6890). RFC Editor. https://doi.org/10.17487/RFC6890

OWASP Foundation. (n.d.). *Server side request forgery prevention cheat sheet*. OWASP Cheat Sheet Series. Retrieved August 5, 2026, from https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html

Python Software Foundation. (2026). *ipaddress—IPv4/IPv6 manipulation library* (Python 3.14.6 documentation). https://docs.python.org/3/library/ipaddress.html
