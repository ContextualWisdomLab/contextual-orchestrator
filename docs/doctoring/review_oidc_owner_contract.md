# Review job identity — owner contract (proposed)

The review gateway owns authentication and request admission. GitHub Actions
owns job identity. A future central broker owns token minting and keeps the
minting capability outside the model process. The gateway accepts only signed
GitHub tokens for its configured audience, org owner ID, and exact central
workflow refs and the immutable central `.github` repository ID. It binds
persisted run ownership to the workload and signed workflow run ID. GitHub's
signed `repository_id` names the repository running the job, which is `.github`
for these central dispatch workflows; it does not identify the reviewed pull
request's repository.
The existing `orchestrator/free` review-only request restrictions still apply.
PyJWT handles JWT/JWK parsing and signature checks through the existing
external-verifier seam; the gateway checks its own workload claims afterward.

## RED → GREEN

- `tests/test_review_oidc.py` first failed to import the missing verifier; it
  now checks signature, issuer, audience, central repo identity, workflow,
  timestamps, unknown keys, and invalid tokens.
- A separate startup test first failed because the OIDC CLI mode was absent;
  it now checks admin/inference separation, admin KV revocation, and refusal
  of mixed static/OIDC inference credentials.
- Corrected the first design against GitHub's OIDC claim definition and the
  central workflow trigger: `repository_id` names `.github`, so a different
  org repository is rejected even if its token names an allowed workflow ref.

## Limits and next gate

This is owner-side source evidence. A hosted token from each actual review
workflow, exact deployed release, isolated broker, TLS ingress, and rollback
have not been verified. Unknown GitHub signing keys are denied until the
five-minute cache refresh; key retrieval failure denies authentication.
Target-repository ownership needs a separate trusted exchange or request
binding with independently verified PR metadata; this OIDC claim cannot supply
it. Per-run ownership prevents one review execution from reading another's
persisted gateway resources, including runs for a different target repository.

The claim set follows [GitHub's OIDC reference](https://docs.github.com/en/actions/reference/security/oidc).
Signature/issuer/audience separation and fixed key retrieval follow
[RFC 8725 §§3.1, 3.8–3.10](https://www.rfc-editor.org/rfc/rfc8725).
The verifier uses [PyJWT's documented JWK client and `decode` API](https://pyjwt.readthedocs.io/en/stable/api.html).
