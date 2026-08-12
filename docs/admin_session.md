# Admin browser sessions

Operators use the `/admin` console without placing the long-lived admin bearer in
JavaScript-readable storage. The browser path is deliberately distinct from the
API bearer path.

## Contract

1. **Establish.** `POST /admin/session` accepts the admin bearer once (JSON
   `{"token": "..."}` or `Authorization: Bearer …`) and mints a high-entropy
   opaque session id stored only in a process-local table
   (`session_id → monotonic expiry`).
2. **Cookie.** The id is returned as `Set-Cookie` with
   `HttpOnly; SameSite=Strict; Path=/; Max-Age=<ttl>`. When the effective origin
   is HTTPS (`X-Forwarded-Proto: https`), the cookie also includes `Secure`.
3. **Authorize.** Admin-scoped routes accept either a valid admin/inference
   bearer (by scope) or an active opaque cookie. The opaque id is **rejected**
   as `Authorization: Bearer`.
4. **Logout / expiry.** `DELETE /admin/session` revokes the server-side record
   and clears the cookie (`Max-Age=0`). Expired ids are purged on use and on
   mint.
5. **Shell.** `GET /` and `GET /admin` serve the static shell **without** auth
   so the operator can open the login gate. All data/API routes remain
   admin-scoped.
6. **Storage.** Session state is **process-local**. A process restart invalidates
   all browser sessions; operators re-authenticate. Multi-replica deployments
   need sticky routing or a shared session backend (not implemented yet).
7. **CSRF.** State-changing admin calls rely on `SameSite=Strict` for
   cross-site request resistance. Cross-origin admin UIs must not be deployed
   against this cookie model without an additional CSRF token scheme.

## Browser UI

The admin console posts the bearer only to `/admin/session`, then uses
`credentials: "same-origin"` for subsequent admin fetches. The bearer is never
written to `localStorage` or `sessionStorage`.

## Research grounding

Browser session hygiene follows established cookie guidance: host-only scoped
session identifiers, `HttpOnly` to block script exfiltration, and `Secure` on
HTTPS origins (Barth, 2011; IETF HTTP State Management Mechanism). Opaque
server-side session ids avoid replaying long-lived API credentials from browser
storage (OWASP Session Management Cheat Sheet).

### References

Barth, A. (2011). *HTTP state management mechanism* (RFC 6265). Internet
Engineering Task Force. https://doi.org/10.17487/RFC6265

OWASP Foundation. (n.d.). *Session management cheat sheet*.
https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html
