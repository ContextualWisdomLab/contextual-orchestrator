- The release checks gate (`scripts/ci/release_checks_gate.sh`) now evaluates
  only the explicit allowlist of the four required `security.yml` checks in
  `RELEASE_EXPECTED_PUSH_CHECKS` ("Tests and package quality", "Property and
  coverage-guided fuzzing", "Rust workspace gate", "CodeQL, supply chain, and
  SBOM"). Check-runs from the hourly `opencode-hourly-loop.yml` and
  `provider-catalog-sync.yml` workflows, and any other non-required check on
  the release commit, no longer block a release. The gate still fails closed
  when a required check is missing, pending, or not `success`, and when the
  allowlist is empty or malformed. Covered by
  `tests/test_release_checks_required_allowlist.py`.
