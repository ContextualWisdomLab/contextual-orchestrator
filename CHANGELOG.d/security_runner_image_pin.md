# Explicit security runner image

The three jobs in `.github/workflows/security.yml` use `ubuntu-24.04` instead of `ubuntu-latest`; the repository metadata regression requires all three fixed labels and rejects the floating label. This is a reproducibility measure, not evidence that an organization-wide runner-capacity or concurrency limit is resolved.

PR #1072 preserves its workflow and regression-test delta. Its release note was moved out of the shared `CHANGELOG.md` insertion point to avoid discarding notes from protected main. The main changelog is preserved verbatim at blob `5adce934a08db3199ce9ca89cbfd7e179f2569a3`; the branch remains a normal descendant of `730801abfc53d46fb377c1be8b48857d89f6588c`.

Integration must retain #1066's stacked-PR trigger, Ready/open admission and PR-scoped cancellation. Older head checks are historical evidence and do not establish integrated-main validation.
