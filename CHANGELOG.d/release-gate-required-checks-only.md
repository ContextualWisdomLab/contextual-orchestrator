- The release checks gate (`scripts/ci/release_checks_gate.sh`) now certifies
  a commit from exactly one workflow run: the newest push-triggered
  `.github/workflows/security.yml` run on `main` for that commit (highest run
  id, then highest `run_attempt`). It evaluates only that run's jobs
  (`filter=latest`) against the explicit allowlist of the four required
  checks in `RELEASE_EXPECTED_PUSH_CHECKS` ("Tests and package quality",
  "Property and coverage-guided fuzzing", "Rust workspace gate", "CodeQL,
  supply chain, and SBOM"). Skipped or failed jobs from scheduled
  `security.yml` runs, the hourly `opencode-hourly-loop.yml` and
  `provider-catalog-sync.yml` runs, and the release run's own jobs no longer
  block a release; the brittle `details_url` self-exclusion is gone. The gate
  fails closed when there is no such run, the run is not completed, a
  required job is missing or not `success`, or the allowlist is empty or
  malformed. The `publish` job gains read-only `actions: read` for the
  recheck. Covered by `tests/test_release_checks_required_allowlist.py`.
