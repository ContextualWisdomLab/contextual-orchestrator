# Architecture Decision Records

ADRs record durable product and technical choices. A PR body or conversation is
evidence, not a decision authority. Status follows [the documentation index](../README.md),
and an active-PR decision is never described as shipped.

| ADR | Decision | Status |
|---|---|---|
| [ADR-0001](0001-route-conduct-test-time-compute.md) | Route versus conduct test-time-compute allocation | `implemented_on_protected_main` |
| [ADR-0002](0002-provider-neutral-transport-trust.md) | Provider-neutral OpenAI-compatible boundary | `accepted_architecture` |
| [ADR-0003](0003-workflow-access-and-reasoning-control.md) | Workflow decomposition, access lists, recursion, and role effort | `accepted_architecture` |
| [ADR-0004](0004-kv-credential-bootstrap.md) | KV credentials and environment-bootstrap-only transport | `implemented_on_protected_main` |
| [ADR-0005](0005-sync-batch-pg-llm-batch.md) | Sync/batch routing and pg-llm-batch integration | `implemented_on_protected_main` |
| [ADR-0006](0006-honest-cost-and-benchmark-evidence.md) | Honest cost/evidence attribution and comparable-budget evaluation | `accepted_architecture` |
| [ADR-0007](0007-free-first-fallback.md) | Free-first fallback and provider-failure semantics | `active_pr` |
| [ADR-0008](0008-state-persistence-and-retention.md) | State/audit persistence and retention | `accepted_architecture` |
| [ADR-0009](0009-purpose-bound-pii-protection.md) | Purpose-bound PII protection without destructive masking | `accepted_architecture` |
| [ADR-0010](0010-independent-review-and-evidence.md) | Independent automated-review identity and evidence separation | `accepted_architecture` |
| [ADR-0011](0011-release-coverage-and-provenance.md) | Release/provenance/SBOM acceptance | `accepted_architecture` |
| [ADR-0012](0012-standalone-and-cwl-boundary.md) | Standalone versus CWL modular authority | `implemented_on_protected_main` |
| [ADR-0013](0013-database-naming-and-migration.md) | Database naming and migration discipline | `accepted_architecture` |
| [ADR-0014](0014-scientific-computation-ownership.md) | Scientific-computation ownership | `out_of_scope` |
| [ADR-0015](0015-provider-egress-response-trust.md) | DNS-pinned egress, redirect/proxy rejection, and bounded response trust | `active_pr` |
| [ADR-0016](0016-complete-coverage-docstrings.md) | Complete production coverage and public-docstring evidence | `accepted_architecture` |

## Minimum decision coverage

The set separately records all required decisions: route/conduct allocation;
provider-neutral compatibility; workflow decomposition/access/effort; KV
credentials; provider transport trust; sync/batch; honest cost and evaluation;
free-first fallback; standalone/CWL authority; state/audit retention;
independent review identities; complete coverage/docstrings; release
provenance/SBOM; and purpose-bound PII. Database migration and scientific
ownership remain additional explicit decisions rather than being hidden in
unrelated ADRs.

## Lifecycle

Create a new ADR when drivers, ownership, compatibility, or recovery changes.
Do not rewrite accepted history to hide a reversal: mark it `superseded`, link
the replacement, and preserve migration and rollback evidence. Each ADR covers
context and drivers, alternatives, decision, consequences, failure/recovery,
security/privacy/governance, compatibility/migration, verification/acceptance,
rollback, and supersession.
