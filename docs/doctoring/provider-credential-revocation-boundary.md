# Provider Credential Revocation Boundary

## Status and scope

This doctoring note defines the fail-closed credential boundary for outbound HTTPS requests made by Contextual Orchestrator to OpenAI-compatible model providers. It applies to the DNS-pinned provider transport used by `ModelClient` and is intentionally narrower than provider-side credential lifecycle management.

The runtime resolves provider secrets from the configured KV backend. Environment variables are not a runtime provider-secret source. The transport uses the HTTP `Authorization` field with the `Bearer` authentication scheme for provider requests.

## Threat model

Provider validation and provider dispatch are separate operations. A credential can be valid when `_validate_provider()` approves the provider endpoint and then be revoked, deleted, or replaced before a later request is serialized.

Before this boundary was added, each dispatch path resolved the credential again but converted a missing value to an empty string while constructing the request. That preserved secret non-disclosure, but it still allowed the HTTPS connection path to proceed with an empty `Authorization: Bearer ` field. The result was an unauthorized outbound network operation after revocation rather than a fail-closed configuration error.

The security property is therefore stronger than “do not leak the old secret”:

> If the provider credential is unavailable at dispatch time, no provider socket may be opened for that request.

This property applies to chat completion, streaming chat, Responses API calls, batch upload, batch metadata operations, and batch content download because all external HTTPS provider egress converges on the DNS-pinned connection class.

## Enforced boundary

`_PinnedHTTPSConnection.request()` is the last application-controlled operation before Python's standard HTTPS request machinery can open a socket. It now requires a present, non-empty Bearer credential before delegating to `http.client.HTTPSConnection.request()`.

The guard is deliberately located at this final pre-socket boundary as defense in depth. `ModelClient` still resolves the current KV value when it builds each request, but the connection layer refuses to turn a missing or empty current value into unauthenticated network traffic.

The failure is `NotConfigured` and the error message does not contain the credential value. The connection object is closed before the exception is raised. No DNS pin, provider hostname, request body, or authorization value is changed by this guard when a non-empty Bearer credential is present.

### Authorization semantics

RFC 9110 defines HTTP field names as case-insensitive and defines the `Authorization` request field within the HTTP authentication framework. The guard therefore locates the authorization field case-insensitively. RFC 6750 defines the Bearer request-header form as the `Bearer` scheme followed by a non-empty credential. Contextual Orchestrator uses that wire form for its OpenAI-compatible provider secret even when the underlying secret is an API key rather than an OAuth access token; RFC 6750 is cited for the Bearer transport grammar, not to claim that every provider key is an OAuth token.

RFC 9700 is the current IETF Best Current Practice updating OAuth 2.0 security guidance. Its emphasis on protecting bearer credentials, limiting token misuse, and maintaining end-to-end TLS is directionally consistent with this fail-closed boundary. The implementation does not claim OAuth conformance beyond the HTTP Bearer transport form used by the provider interface.

## Authority and compatibility boundary

The normal external-provider contract remains HTTPS-only, DNS-pinned, proxy-bypassing, redirect-rejecting, and certificate-verified against the original provider hostname. Credential revocation handling does not weaken any of those controls.

The private plain-HTTP loopback seam remains a narrowly scoped local integration/test capability. Production provider validation rejects plain HTTP before external credentials are dispatched, so the pre-socket Bearer guard is intentionally implemented on the external DNS-pinned HTTPS connection rather than changing local loopback behavior.

If a future provider transport requires an authentication scheme other than Bearer, it must introduce that scheme explicitly with provider-specific tests and an equivalent fail-closed pre-socket credential check. Removing this guard merely to make a non-Bearer provider work is not an acceptable compatibility fix.

## Regression evidence

`tests/test_provider_credential_revocation.py` provides three bounded contracts:

1. A provider credential is valid during DNS validation, the active KV backend is then replaced with one that does not contain the credential, and all six external provider request paths must raise `NotConfigured` before `socket.create_connection` can execute.
2. A direct DNS-pinned request with no authorization evidence must fail before the base HTTPS request method is called.
3. A request carrying a non-empty Bearer credential must delegate unchanged to the standard HTTPS request machinery.

The test-first lineage is preserved in pull-request history: the regression was introduced before the production transport guard. Repository-local workflow results prove only the exact commit they ran against and do not substitute for central coverage, security review, branch protection, or independent approval.

## Operator behavior

A `NotConfigured` failure at this boundary means the request was intentionally prevented from reaching the provider because current authentication evidence was unavailable. Operators should:

1. verify that the configured KV backend is the intended backend for the runtime;
2. verify that the agent's credential name exists and contains a non-empty current value;
3. complete the intended rotation or restore the credential through the approved secret-management path; and
4. retry only after the credential state is correct.

Do not work around this failure by adding an environment fallback, a blank credential, a proxy exception, disabling TLS verification, or changing the provider URL to plain HTTP.

## Rollback

Rollback is appropriate only if the provider authentication contract itself is intentionally redesigned. A rollback must preserve the core invariant that unavailable current credential evidence cannot open an external provider socket. Any replacement must include equivalent regression tests for every provider egress family before this guard is removed.

## References

Fielding, R., Nottingham, M., & Reschke, J. (Eds.). (2022). *HTTP semantics* (RFC 9110; STD 97). Internet Engineering Task Force. https://doi.org/10.17487/RFC9110

Jones, M., & Hardt, D. (2012). *The OAuth 2.0 authorization framework: Bearer token usage* (RFC 6750). Internet Engineering Task Force. https://doi.org/10.17487/RFC6750

Lodderstedt, T., Bradley, J., Labunets, A., & Fett, D. (2025). *Best current practice for OAuth 2.0 security* (RFC 9700; BCP 240). Internet Engineering Task Force. https://doi.org/10.17487/RFC9700
