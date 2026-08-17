# Architecture Decision Records

ADRs record durable product and technical choices for Contextual Orchestrator.
A pull-request body or chat is evidence, not a decision authority.

Status on this page describes **protected `main`**, not an unmerged branch.
`implemented_on_protected_main` means the decision is visible in the current
runtime. `accepted_architecture` means the decision governs design even when
some production controls remain incomplete. `not_implemented_on_protected_main`
means the decision is recorded and must not be described as shipped.
`out_of_scope` means this repository does not own the capability.

Research citations use APA 7th edition with a DOI or canonical URL. Verified
orchestration papers are Xu et al. (TRINITY) and Nielsen et al. (Conductor).
Do not invent Zhang or Li as authors of those works. arXiv “to appear”
comments are not treated as a final proceedings record. Full entries live in
[docs/REFERENCES.md](../REFERENCES.md).

Naruon and gyeot are composition hubs. This orchestrator may be called by
them. That composition is not a microservices-architecture violation. Sibling
links stay; see [ADR-0012](0012-standalone-and-cwl-boundary.md).

| ADR | Decision | Status |
|---|---|---|
| [ADR-0001](0001-route-conduct-test-time-compute.md) | Route versus conduct test-time-compute allocation | `implemented_on_protected_main` |
| [ADR-0002](0002-provider-neutral-transport-trust.md) | Provider-neutral OpenAI-compatible boundary | `implemented_on_protected_main` |
| [ADR-0003](0003-workflow-access-and-reasoning-control.md) | Workflow decomposition and access lists | `implemented_on_protected_main` |
| [ADR-0004](0004-kv-credential-bootstrap.md) | KV credentials; environment is bootstrap only | `implemented_on_protected_main` |
| [ADR-0005](0005-sync-batch-pg-llm-batch.md) | Sync/batch routing and optional pg-llm-batch | `implemented_on_protected_main` |
| [ADR-0006](0006-honest-cost-and-benchmark-evidence.md) | Honest cost and measurement provenance | `implemented_on_protected_main` |
| [ADR-0007](0007-free-first-fallback.md) | Free-first fallback without invented availability | `not_implemented_on_protected_main` |
| [ADR-0008](0008-state-persistence-and-retention.md) | Opt-in state persistence and retention | `accepted_architecture` |
| [ADR-0009](0009-purpose-bound-pii-protection.md) | Purpose-bound PII protection | `accepted_architecture` |
| [ADR-0010](0010-independent-review-and-evidence.md) | Independent review and evidence authority | `accepted_architecture` |
| [ADR-0011](0011-release-coverage-and-provenance.md) | Release coverage, SBOM, and provenance | `accepted_architecture` |
| [ADR-0012](0012-standalone-and-cwl-boundary.md) | Standalone product and CWL composition | `implemented_on_protected_main` |
| [ADR-0013](0013-database-naming-and-migration.md) | Database naming and evidence-driven migration | `accepted_architecture` |
| [ADR-0014](0014-scientific-computation-ownership.md) | Scientific-computation ownership | `out_of_scope` |
| [ADR-0015](0015-provider-egress-response-trust.md) | Provider egress and response trust | `accepted_architecture` |
| [ADR-0016](0016-complete-coverage-docstrings.md) | Coverage and public-docstring evidence | `accepted_architecture` |

## Change rule

Create or update an ADR when drivers, ownership, compatibility, recovery,
credential trust, or a paper/standard mapping changes. Do not rewrite accepted
history to hide a reversal: mark it `superseded`, link the replacement, and
preserve migration evidence.

Each ADR covers context and drivers, alternatives, decision, consequences,
failure/recovery, security/privacy/governance, compatibility/migration,
verification, rollback, and verified references.

## Related operator docs

- [Architecture notes](../architecture.md)
- [Papers grounding the cost-review hub](../papers/README.md)
- [KV credentials](../kv-credentials.md)
- [Library research](../library_research.md)
