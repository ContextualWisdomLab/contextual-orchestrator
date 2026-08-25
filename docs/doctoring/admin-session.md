# Browser admin session doctoring

## Customer next action

Run the admin console behind HTTPS, establish a session once with the admin
bearer, and then use the console without placing that bearer in browser
storage. Configure `admin_session_secure_cookie=False` (or the CLI's
`--insecure-admin-session-cookie`) only for an explicitly isolated local HTTP
test; production and reverse-proxy deployments keep the secure cookie default.

## Contract

- `POST /admin/session` accepts a bearer in the JSON body or `Authorization`
  header, validates it, and returns only `session_status=established`.
- The `contextual_orchestrator_session` cookie is an opaque server-side id;
  the raw bearer is never stored in the session map or returned in a response.
- The cookie is `HttpOnly`, `SameSite=Strict`, bounded by TTL and maximum live
  sessions, and `Secure` by default.
- `DELETE /admin/session` revokes the current cookie and clears it.
- Admin session cookies authorize admin scope only. They cannot call inference
  endpoints as bearer credentials.
- Cookie-authenticated state-changing requests require an `Origin` whose
  network location equals `Host`; API bearer clients remain compatible.
- Session state is process-local. A multi-process or durable session backend is
  a future deployment boundary, not an unstated reliability claim.

## Evidence

`tests/test_security_hardening.py` proves opacity, admin-only scope, cross-origin
state-change rejection, logout revocation, and cookie clearing. The admin
surface contract proves the UI uses same-origin credentials and clears the
entered token. Focused verification for this change is recorded in the PR;
hosted security and full-suite checks remain authoritative.

## Design provenance

The implementation uses a server-side opaque session id instead of masking or
transforming business PII. Authorization, purpose, expiry, revocation, and
audit boundaries protect access while preserving authorized data usability.
The existing admin design source is Figma file `vsZMd8WAv42HDRgcZuNcWk`.
Storybook is not introduced because this repository has no standalone frontend
package; the embedded admin shell remains covered by its HTML contract test.

## References

National Institute of Standards and Technology. (2022). *Digital identity
guidelines: Authentication and lifecycle management (NIST Special Publication
800-63B)*. https://doi.org/10.6028/NIST.SP.800-63b

OWASP Foundation. (n.d.). *Session management cheat sheet*. Retrieved August
20, 2026, from https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html

Barth, A. (2011). *HTTP state management mechanism* (RFC 6265). Internet
Engineering Task Force. https://doi.org/10.17487/RFC6265
