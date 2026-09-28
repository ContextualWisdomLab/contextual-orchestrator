# Review job identity — owner contract (proposed)

The review gateway owns authentication and request admission. GitHub Actions
owns job identity. A future central broker owns token minting and keeps the
minting capability outside the model process. The gateway accepts only signed
GitHub tokens for its configured audience, org owner ID, and exact central
workflow refs. OpenCode dispatch runs in `.github` and requires its immutable
repository ID. Org-required Noema and Strix workflows also run in the target
repository; their signed repository ID names that running repository. Persisted
run ownership uses workload, signed running-repository ID, and workflow run ID.
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
- Corrected the initial single-repository assumption against the live workflow
  runs. OpenCode's central dispatch uses `.github`; Noema and Strix required
  workflows can run in the reviewed repository. The verifier restricts
  OpenCode to the central repository and accepts a signed org repository for
  Noema/Strix, while requiring the configured central workflow ref in both cases.
- GitHub run metadata for Strix `36384628946` and Noema `36384628839` on
  contextual-orchestrator #1227 reports `repository=ContextualWisdomLab/contextual-orchestrator`
  and the expected workflow paths. This establishes the running
  repository for those runs; no OIDC token from either job was captured.

## Limits and next gate

This is owner-side source evidence. A hosted token from each actual review
workflow, exact deployed release, isolated broker, TLS ingress, and rollback
have not been verified. Unknown GitHub signing keys are denied until the
five-minute cache refresh; key retrieval failure denies authentication.
For a central Noema or Strix dispatch, `repository_id` still names `.github`;
target-repository ownership needs a separate trusted binding with verified PR
metadata. A signed running-repository ID plus run ID prevents one native review
execution from reading another's persisted gateway resources.

The claim set follows [GitHub's OIDC reference](https://docs.github.com/en/actions/reference/security/oidc).
Signature/issuer/audience separation and fixed key retrieval follow
[RFC 8725 §§3.1, 3.8–3.10](https://www.rfc-editor.org/rfc/rfc8725).
The verifier uses [PyJWT's documented JWK client and `decode` API](https://pyjwt.readthedocs.io/en/stable/api.html).
