# Review job identity — owner contract (proposed)

The review gateway owns authentication and request admission. GitHub Actions
owns job identity. A future central broker owns token minting and keeps the
minting capability outside the model process. The gateway accepts only signed
GitHub tokens for its configured audience, org owner ID, and exact central
workflow refs; it binds persisted run ownership to workload plus target repo ID.
The existing `orchestrator/free` review-only request restrictions still apply.
PyJWT handles JWT/JWK parsing and signature checks through the existing
external-verifier seam; the gateway checks its own workload claims afterward.

## RED → GREEN

- `tests/test_review_oidc.py` first failed to import the missing verifier; it
  now checks signature, issuer, audience, org/target identity, workflow,
  timestamps, unknown keys, and invalid tokens.
- A separate startup test first failed because the OIDC CLI mode was absent;
  it now checks admin/inference separation, admin KV revocation, and refusal
  of mixed static/OIDC inference credentials.
- Corrected the first design after reading central workflow triggers: the
  workflow can run under a target repository, so its token cannot be pinned to
  `.github`'s repository ID. The configured trust anchor is the immutable org
  owner ID plus the central workflow ref; the signed target ID scopes ownership.

## Limits and next gate

This is owner-side source evidence. A hosted token from each actual review
workflow, exact deployed release, isolated broker, TLS ingress, and rollback
have not been verified. Unknown GitHub signing keys are denied until the
five-minute cache refresh; key retrieval failure denies authentication.

The claim set follows [GitHub's OIDC reference](https://docs.github.com/en/actions/reference/security/oidc).
Signature/issuer/audience separation and fixed key retrieval follow
[RFC 8725 §§3.1, 3.8–3.10](https://www.rfc-editor.org/rfc/rfc8725).
The verifier uses [PyJWT's documented JWK client and `decode` API](https://pyjwt.readthedocs.io/en/stable/api.html).
