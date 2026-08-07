# Security Policy

This policy defines the public vulnerability-reporting and coordinated-disclosure boundary for `ContextualWisdomLab/contextual-orchestrator`. It is informed by ISO/IEC 29147:2018 for vulnerability disclosure and ISO/IEC 30111:2019 for vulnerability handling. The evidence basis and review dates are recorded in `docs/doctoring/security-disclosure-lifecycle.md`.

## Supported Versions

Security fixes are prepared for the latest supported release and, when a vulnerability materially affects an older release that is still explicitly supported, for that supported line as well. Development branches, historical tags, archived artifacts, forks, and unreleased commits are not represented as supported production versions merely because they remain accessible.

When no stable release has been published, `main` is the integration reference but is not itself a release-support promise. A GitHub Security Advisory or release advisory is the authoritative place to identify affected and patched versions for a specific vulnerability.

## Scope

In scope are vulnerabilities in this repository's maintained source, packaging, release artifacts, provider-neutral orchestration interfaces, authentication and credential boundaries, network egress controls, persistence boundaries, and first-party GitHub Actions workflows.

Reports about third-party services or dependencies are useful when they demonstrate an impact on this project, but upstream-only defects should normally be reported to the responsible upstream maintainer. Findings in unrelated ContextualWisdomLab repositories should be reported through those repositories' own security channels. Do not use a vulnerability report as authorization to test third-party infrastructure, access data that is not yours, degrade service, or bypass provider terms.

## Reporting a Vulnerability

Use GitHub private vulnerability reporting for `ContextualWisdomLab/contextual-orchestrator` whenever it is available:

https://github.com/ContextualWisdomLab/contextual-orchestrator/security/advisories/new

A useful report includes the affected component and version or commit, prerequisites, reproducible steps, observed impact, expected impact boundary, and any safe proof-of-concept material needed to validate the issue. Remove credentials, personal data, private model reasoning, and unrelated customer or provider data.

If private reporting is unavailable, open a public issue that contains only a request for a secure disclosure channel. Do not include exploit details, secrets, personal data, or unreleased vulnerability details in a public issue.

## Coordinated Disclosure Lifecycle

1. **Receive and acknowledge.** Maintainers triage a private report and aim to acknowledge a credible report within 5 business days. This acknowledgement target is a communication objective, not a remediation SLA and not a promise that validation or a fix will complete within five days.
2. **Validate and scope.** Maintainers reproduce the report where practical, classify affected versions and deployment assumptions, identify downstream or multi-vendor coordination needs, and keep unpatched technical details private.
3. **Remediate and verify.** A fix is developed through a private security collaboration or another access-controlled path when premature disclosure would increase risk. Security-sensitive fixes must retain the repository's tests, coverage, security scanning, provenance, branch-protection, and independent-review requirements rather than bypass them.
4. **Coordinate release.** Maintainers and the reporter coordinate a disclosure point that reasonably allows a verified fix or mitigation to be available. Multi-vendor issues may require additional coordination time.
5. **Publish evidence.** When disclosure is appropriate, publish a GitHub Security Advisory and release or upgrade guidance that identifies affected versions, impact, remediation or mitigation, and patched versions. Request a CVE through the applicable advisory process when warranted and available.
6. **Learn and prevent recurrence.** Record the relevant root-cause class, regression evidence, and preventive control without publishing credentials, private data, or unnecessary exploit-enabling detail.

Reporter credit is offered when requested and appropriate, subject to the reporter's preference, coordinated-disclosure needs, and GitHub advisory capabilities. A reporter may also request not to be credited.

## Safe Harbor and Research Boundaries

We support good-faith security research that stays within the scope above, avoids privacy violations and service degradation, uses the minimum access needed to demonstrate the issue, stops when unintended sensitive data is encountered, and gives maintainers a reasonable opportunity to remediate before public disclosure. This policy does not authorize activity against third-party systems, physical systems, accounts or data you do not control, or conduct prohibited by applicable law or provider terms.

Do not intentionally persist, download, modify, or disclose data that is not yours. Do not perform denial-of-service testing, social engineering, credential stuffing, destructive testing, or high-volume automated probing against production services. If testing unexpectedly exposes sensitive information, stop, preserve only the minimum evidence needed to report the issue, and disclose it privately.

## Advisory and Release Evidence

A vulnerability is not considered remediated merely because a patch exists on a branch. Release evidence must identify the exact integrated and released revision and must not treat queued, pending, skipped-required, cancelled, absent, failed, stale-head, predecessor-head, or synthetic-merge-only checks as passing evidence. Security advisories should identify the affected and patched version ranges and link to release or upgrade guidance when practical.

This policy does not replace repository merge policy: qualifying independent review, unresolved-finding disposition, required checks, branch protection, packaging, provenance, and release-acceptance controls remain authoritative for security releases.

## Automated Checks

The `Security` GitHub Actions workflow runs CodeQL, dependency review, pip-audit against the hash-pinned `requirements.lock`, CycloneDX SBOM generation, Trivy filesystem scanning, and OpenSSF Scorecard checks on the configured branch, pull request, schedule, and manual triggers. Third-party GitHub Actions and Python security-tool installers in `requirements-security-ci.txt` are pinned to reviewed commit SHAs or hash-locked package requirements with source files kept for maintenance.
