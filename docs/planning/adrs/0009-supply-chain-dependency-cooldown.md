---
id: "0009"
title: "Add an explicit Dependabot dependency cooldown"
status: accepted
proposed_date: "2026-08-11"
accepted_date: "2026-08-11"
deciders:
  - "repository maintainer"
consulted:
  - "Strix security scan"
  - "GitHub Dependabot configuration"
informed:
  - "contributors"
affected_components:
  - ".github/dependabot.yml"
  - "tests/test_repository_security_metadata.py"
  - "docs/planning/adrs/"
effort: S
supersedes: null
superseded-by: null
related:
  - path: "docs/planning/adrs/0004-pr-review-merge-loop.md"
    relation: informational
  - path: "docs/planning/adrs/0007-sast-transport-and-sql-hardening.md"
    relation: informational
asr_triggers:
  - kind: security
    evidence: "The current-head Strix scan reported a critical Dependabot cooldown finding in .github/dependabot.yml, alongside provider failures that required fail-closed handling."
    note: "Make dependency-update timing an explicit repository policy and retain the security scan as the validation gate."
  - kind: maintainability
    evidence: "A scanner finding exposed an implicit dependency-update policy that was not protected by repository metadata tests."
    note: "Keep the setting adjacent to each ecosystem and assert both entries in the repository security metadata test."
success_criteria:
  - metric: "dependency update cooldown"
    target: "GitHub Actions and pip Dependabot update entries each declare cooldown.default-days: 7"
    measurement_window: "every Dependabot configuration review and security scan"
    source: ".github/dependabot.yml and tests/test_repository_security_metadata.py"
---

# Add an explicit Dependabot dependency cooldown

## Context

The current-head Strix scan for PR #109 produced a structured critical finding
against the repository's dependency-update configuration. The finding targeted
the absence of an explicit cooldown for newly published package versions.

> Strix reported `package_managers.dependabot.dependabot-missing-cooldown.dependabot-missing-cooldown` with high confidence.
> The finding recommended a seven-day cooldown for each update ecosystem.
> GitHub's current Dependabot options document `cooldown.default-days` as the explicit setting for supported package managers and distinguish version-update cooldown from security updates.

## Decision Drivers

* Reduce exposure to newly published malicious or unstable dependency versions.
* Keep the policy explicit and reviewable for both configured ecosystems.
* Preserve timely Dependabot security updates and avoid adding a dependency-management tool.

## Considered Options

* Leave the implicit platform default and accept scanner noise.
* Add an explicit seven-day cooldown to every configured ecosystem.
* Disable Dependabot version updates and manage all updates manually.

## Decision Outcome

Chosen option: "Declare a seven-day cooldown for GitHub Actions and pip version updates".

| Driver | Implicit default | Explicit seven-day cooldown | Disable automated updates |
| --- | --- | --- | --- |
| Supply-chain exposure window | Unclear and scanner-visible | Bounded and reviewable | Manual process can drift |
| Security updates | Platform behavior remains implicit | Security updates remain outside version cooldown | Delayed by human workflow |
| Maintenance cost | Low now, weak evidence | One small config and metadata assertion | High |

Each `github-actions` and `pip` update entry in `.github/dependabot.yml` now has
`cooldown.default-days: 7`. This applies to version-update proposals; it does
not disable or intentionally delay Dependabot security updates. The repository
metadata test asserts that both ecosystems retain the explicit setting.

## Problem Register and Remediation Directions

| Finding | Direction | State |
| --- | --- | --- |
| Dependabot entries had no explicit cooldown and Strix reported a critical supply-chain finding. | Add `cooldown.default-days: 7` to every configured ecosystem and protect both entries with a repository metadata regression test. | Implemented in current head |
| An external scanner finding could be mistaken for provider noise. | Keep the Strix gate fail-closed and inspect structured artifacts separately from provider 429/410 evidence. | Implemented in current review loop |

## Risks and Mitigations

| risk | likelihood | impact | mitigation | owner |
| --- | --- | --- | --- | --- |
| A seven-day delay postpones a non-security version update. | low | medium | Keep Dependabot security updates enabled and review urgent version updates explicitly. | maintainer |
| A future ecosystem entry omits the cooldown. | medium | high | Require one `default-days: 7` entry per configured ecosystem in the metadata test and Strix review. | maintainer |

## Rollback / Exit Strategy

If a documented dependency requires a shorter version-update window, change the
specific ecosystem cooldown only through a reviewed ADR update and retain the
security-update path. Do not remove the explicit setting to silence a scanner.

## Affected Components

* .github/dependabot.yml
* tests/test_repository_security_metadata.py
* docs/planning/adrs/0009-supply-chain-dependency-cooldown.md

## More Information

* [GitHub Dependabot options reference](https://docs.github.com/en/code-security/reference/supply-chain-security/dependabot-options-reference)
* [GitHub guidance on dependency update cooldown](https://docs.github.com/en/code-security/tutorials/secure-your-dependencies/optimizing-pr-creation-version-updates)
