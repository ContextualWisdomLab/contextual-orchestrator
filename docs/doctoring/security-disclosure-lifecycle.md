# Security disclosure lifecycle doctoring

## Decision

`SECURITY.md` defines a bounded coordinated vulnerability disclosure and handling lifecycle rather than only a reporting address. The policy separates communication targets from remediation guarantees, keeps unpatched details private, preserves repository release gates for security fixes, and identifies exact released-version evidence as the authoritative remediation boundary.

The policy is intentionally repository-local. It does not authorize testing of third-party providers or other ContextualWisdomLab repositories and does not convert access to public endpoints into permission for destructive, privacy-invasive, or high-volume testing.

## Primary evidence reviewed

Evidence was rechecked on 2026-08-08 against primary publisher documentation.

### ISO/IEC 29147:2018

ISO identifies ISO/IEC 29147:2018, *Information technology — Security techniques — Vulnerability disclosure*, as the current published second edition. ISO states that the standard provides requirements and recommendations for receiving reports about potential vulnerabilities and disclosing remediation information. ISO's catalogue states that this edition was last reviewed and confirmed in 2024 and remains current. This supports a documented private-reporting path, disclosure coordination, affected/remediated-version communication, and explicit policy boundaries.

### ISO/IEC 30111:2019

ISO identifies ISO/IEC 30111:2019, *Information technology — Security techniques — Vulnerability handling processes*, as the current published second edition. ISO states that it covers processing and remediating reported potential vulnerabilities. ISO's catalogue states that this edition was reviewed and confirmed in 2025 and remains current. This supports the receive → validate/scope → remediate/verify → coordinate release → publish → learn lifecycle in `SECURITY.md`.

### GitHub vulnerability reporting and repository advisories

GitHub's current documentation describes GitHub private vulnerability reporting as a structured private channel for public repositories when the feature is enabled. GitHub also documents the repository security advisory workflow as a private collaboration mechanism for discussing, fixing, and publishing vulnerability information. GitHub recommends that `SECURITY.md` explain supported versions and reporting instructions. These sources support the repository's primary reporting URL, public-issue fallback that contains no exploit detail, private remediation collaboration, reporter credit, and advisory publication boundary.

### NIST SSDF status

NIST SP 800-218 Rev. 1, Secure Software Development Framework Version 1.2, is currently an **Initial Public Draft**, published 2025-12-17; its public comment period has closed. It is therefore contextual acquisition and secure-development evidence, not a finalized normative requirement. NIST describes SSDF as a common set of practices for reducing vulnerabilities and notes its usefulness in supplier/acquirer communication. The repository policy uses that evidence only to reinforce the need for verified remediation and release evidence; ISO/IEC 29147 and ISO/IEC 30111 remain the primary disclosure/handling standards cited by the policy.

## Repository contract

The bounded buyer-visible contract is:

1. The latest supported release is the default support boundary; an advisory may explicitly include additional supported release lines.
2. `main`, development branches, archived artifacts, forks, and historical tags are not automatically represented as supported releases.
3. Private vulnerability reporting is the preferred channel. If unavailable, a public issue may request a secure channel but must not disclose exploit details, secrets, personal data, or unreleased vulnerability details.
4. The five-business-day acknowledgement target is a communication objective and **not a remediation SLA**.
5. Security remediation follows normal exact-head security, coverage, provenance, independent-review, branch-protection, packaging, and release-acceptance gates; urgency does not create a bypass.
6. A GitHub Security Advisory should identify affected and patched versions and may request a CVE when warranted and available.
7. Reporter credit is opt-in/appropriate to the coordinated-disclosure context and may be declined.
8. Release evidence fails closed: queued, pending, skipped-required, cancelled, absent, failed, stale-head, predecessor-head, or synthetic-merge-only check evidence is not passing evidence.
9. The safe-harbor language is bounded good-faith guidance, not authorization against third parties or systems/data the researcher does not control.

## Verification

`tests/test_repository_security_metadata.py::test_security_policy_documents_coordinated_disclosure_lifecycle` locks the buyer-visible policy vocabulary and this evidence receipt. The test is deliberately documentation-focused: it prevents future edits from silently deleting the supported-version boundary, lifecycle, non-SLA qualification, advisory/CVE path, reporter-credit expectation, public-reporting safety rule, or standards provenance.

This slice does not change production runtime code, provider behavior, credentials, workflows, database objects, or release state. It also does not modify the central `.github` control plane or depend on unmerged central coverage logic.

## References (APA 7)

GitHub. (n.d.). *Adding a security policy to your repository*. GitHub Docs. Retrieved August 8, 2026, from https://docs.github.com/en/code-security/how-tos/report-and-fix-vulnerabilities/configure-vulnerability-reporting/add-security-policy

GitHub. (n.d.). *Coordinated disclosure of security vulnerabilities*. GitHub Docs. Retrieved August 8, 2026, from https://docs.github.com/en/code-security/concepts/vulnerability-reporting-and-management/coordinated-disclosure

GitHub. (n.d.). *Privately reporting a security vulnerability*. GitHub Docs. Retrieved August 8, 2026, from https://docs.github.com/en/code-security/how-tos/report-and-fix-vulnerabilities/report-privately

GitHub. (n.d.). *Repository security advisories*. GitHub Docs. Retrieved August 8, 2026, from https://docs.github.com/en/code-security/concepts/vulnerability-reporting-and-management/repository-security-advisories

International Organization for Standardization. (2018). *ISO/IEC 29147:2018 Information technology—Security techniques—Vulnerability disclosure* (2nd ed.). https://www.iso.org/standard/72311.html

International Organization for Standardization. (2019). *ISO/IEC 30111:2019 Information technology—Security techniques—Vulnerability handling processes* (2nd ed.). https://www.iso.org/standard/69725.html

National Institute of Standards and Technology. (2025). *Secure software development framework (SSDF) version 1.2: Recommendations for mitigating the risk of software vulnerabilities* (NIST SP 800-218 Rev. 1, Initial Public Draft). https://csrc.nist.gov/pubs/sp/800/218/r1/ipd

## APA 7 note

The references above use organizational authors for standards and first-party documentation. Retrieval dates are included for GitHub pages because operational documentation can change without a new edition identifier. ISO edition years and NIST publication status are retained as publisher-controlled version evidence.
