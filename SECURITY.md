# Security Policy

## Reporting a Vulnerability

Report suspected vulnerabilities through GitHub private vulnerability reporting for `ContextualWisdomLab/contextual-orchestrator`: https://github.com/ContextualWisdomLab/contextual-orchestrator/security/advisories/new

If private reporting is unavailable, open a public issue that contains only a request for a secure disclosure channel. Do not include exploit details, secrets, personal data, or unreleased vulnerability details in a public issue.

## Response Process

- A maintainer should acknowledge a valid private report within 5 business days.
- Security fixes should be handled on a private branch until the patch is ready to publish.
- Public disclosure should include affected versions, impact, mitigation, and upgrade guidance.

## Automated Checks

The `Security` GitHub Actions workflow runs CodeQL, dependency review, hash-pinned `pip-audit` and CycloneDX tooling from `requirements-security-tools.txt`, pip-audit against the hash-pinned `requirements.lock`, CycloneDX SBOM generation, Trivy filesystem scanning, and OpenSSF Scorecard checks on the configured branch, pull request, schedule, and manual triggers. Third-party GitHub Actions in the workflow are pinned to reviewed commit SHAs with the source tag kept in comments for maintenance.
