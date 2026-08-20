# Workflow-run object authorization doctoring

## Root cause

Admin authentication protected workflow-run, access-report, and evaluation-run
routes, but the requested identifier was not bound to the authenticated
principal. Any principal with the admin scope could therefore enumerate or
retrieve another principal's run identifier.

## Implemented contract

- Each authenticated bearer produces a stable SHA-256 owner key; the token is
  never persisted or returned.
- Synchronous, streamed, workflow, and evaluation records carry that owner key.
- Run lists, run details, access reports, and evaluation details filter by the
  owner key and return the same not-found result for an unauthorized ID.
- Owner keys are removed recursively from public response bodies.
- Existing direct library calls remain backward compatible when no owner key is
  supplied; the HTTP boundary always supplies one after authentication.

## Verification

```bash
uv run pytest tests/test_workflow_run_object_authorization.py -q
python -m compileall -q contextual_orchestrator
git diff --check
```

## References

Open Worldwide Application Security Project. (2023). *OWASP API Security Top
10: 2023 (API1:2023 Broken Object Level Authorization).*
https://owasp.org/API-Security/editions/2023/en/0xa1-broken-object-level-authorization/

National Institute of Standards and Technology. (2020). *Digital identity
guidelines: Authentication and lifecycle management* (SP 800-63B).
https://doi.org/10.6028/NIST.SP.800-63b
