# Commercial Security Attestation

Runtime endpoint: `/api/v1/commercial_security_attestations/latest`.

This document defines the buyer security-review attestation gate for a
KRW 2,000,000,000 buyer packet. It separates repo-local security evidence from
external attestation, hosted scan output, and buyer privacy inputs. It is not a
valuation guarantee, purchase commitment, legal opinion, production compliance
certificate, or third-party security audit.

Figma Code Connect is not used.

Review process is not a blocker. Reviewer delay, review bot delay, queued model
review, and pending checks without a concrete failure are not blockers. Blockers
are concrete security failures, API contract failures, document contract
mismatches, reproducible product defects, or Code Connect usage.

Do not create a separate library, Git submodule, or extracted package now. Keep
Contextual Orchestrator as one enterprise control-plane product until a second
product, independent release cadence, or buyer security provenance requirement
creates an extraction trigger.

## Security Attestation Inputs

| Input | Source | Purpose |
| --- | --- | --- |
| Commercial operations readiness | `/api/v1/commercial_operations_readiness/latest` | Primary handoff, review-process, and packaging source. |
| Commercial evidence export | `/api/v1/commercial_evidence_exports/latest` | Portable buyer evidence source. |
| Security policy | `SECURITY.md` | Vulnerability reporting and support scope evidence. |
| Dependency and package metadata | `requirements.lock`, `pyproject.toml` | Supply-chain review baseline. |
| Security workflow metadata | `.github/workflows/security.yml`, `.github/workflows/scorecard-analysis.yml`, `.github/dependabot.yml` | CI security controls and dependency update metadata. |
| Runtime access controls | `contextual_orchestrator/server.py` | Admin/inference auth, trace exposure, rate limit, and concurrency evidence. |

## Runtime Shape

`/api/v1/commercial_security_attestations/latest` returns:

- `security_attestation_status`:
  `commercial_security_attestation_ready`,
  `commercial_security_attestation_ready_with_warnings`, or
  `commercial_security_attestation_blocked`;
- `measurement_status`: `local_commercial_security_attestation`;
- `security_attestation_summary`: ready, warning, blocked, external
  attestation gap, buyer privacy gap, and review-process blocker counts;
- `security_attestation_items`: security policy, dependency lock/package
  metadata, security workflow metadata, runtime access-control profile,
  audit/export evidence, vulnerability scan evidence, third-party attestation
  or penetration test, buyer privacy/DPA questionnaire input, review-process
  policy, and packaging decision;
- `concrete_blockers`: only concrete product, security, API contract, document,
  or Code Connect failures;
- `security_attestation_status_rules`: stable ready/warning/blocked rules;
- `related_runtime_reports`: operations, onboarding, contract, procurement,
  gap-register, release-candidate, and acceptance context;
- `library_split_decision`: current single-product packaging decision;
- `plugin_traceability`: Figma, Product Design, Superpowers, Ponytail, and Data
  Analytics responsibilities;
- `security_attestation_links`: editable Figma/FigJam links, endpoint, and
  documentation.

## Security Attestation Status Rules

| Status | Rule |
| --- | --- |
| `commercial_security_attestation_ready` | Security policy, dependency metadata, workflow metadata, access controls, audit export, external attestation, buyer privacy input, review policy, and packaging evidence are ready. |
| `commercial_security_attestation_ready_with_warnings` | Repo-local security packet is ready while hosted scan evidence, third-party attestation, or buyer privacy input remains explicit warnings. |
| `commercial_security_attestation_blocked` | Missing local security packet evidence, concrete product defect, API contract failure, security failure, document mismatch, or Code Connect usage blocks security attestation. |

## KRW 2B Commercial Security Attestation

The repository can package a security-review packet without pretending that
external attestations or buyer-specific privacy terms already exist:

- `SECURITY.md` gives the buyer a vulnerability reporting and supported-scope
  source;
- `requirements.lock` and `pyproject.toml` give the buyer a dependency and
  package-metadata baseline;
- security workflow metadata defines Dependabot, CodeQL, dependency review,
  pip-audit, SBOM, Trivy, and OSSF Scorecard controls;
- runtime access controls expose admin/inference auth mode, public bind opt-in,
  trace exposure default, rate limit, and concurrency controls;
- audit/export evidence maps the security packet back to
  `/api/v1/commercial_evidence_exports/latest`;
- vulnerability scan evidence remains an external-attestation warning until the
  latest hosted scan outputs are attached or waived;
- third-party attestation or penetration-test evidence remains an
  external-attestation warning until the buyer accepts the evidence, assessment,
  or waiver;
- buyer privacy, DPA, data residency, and questionnaire answers remain buyer
  input warnings until deal-specific terms are known;
- review-process delay remains non-blocking until a concrete failure appears;
- single-product packaging remains the default until a real extraction trigger
  exists.

## Plugin Traceability

| Plugin | Security-attestation responsibility |
| --- | --- |
| Product Design | Keep security attestation visible in the existing admin observability surface. |
| Figma | Record the editable FigJam flow named `KRW 2B Commercial Security Attestation`. |
| Data Analytics | Label security metrics as repo-local evidence or external/buyer-required inputs. |
| Superpowers | Maintain the implementation plan, acceptance checks, and concrete blocker rules. |
| Ponytail | Keep one deployable product and avoid package extraction before a trigger. |

## Verification

```bash
python tests/test_commercial_security_attestation.py
python tests/test_commercial_operations_readiness.py
python tests/test_api_contract.py
python tests/test_plugin_driven_artifacts.py
pytest -q
```
