# Authoritative documentation

This index is the entry point for product, technical, operational, and
governance decisions. Conversation history, issue descriptions, pull-request
bodies, and implementation plans are evidence, not the product source of truth.

## Status vocabulary

Every capability and decision uses one of these states.

| State | Meaning |
|---|---|
| `implemented_on_protected_main` | The behavior exists on protected `main` and has repository evidence. |
| `active_pr` | The behavior exists only on an open pull request and is not shipped. |
| `accepted_architecture` | The direction is accepted, but implementation may be partial. |
| `planned` | The work is prioritized but not accepted as implemented. |
| `research_only` | The repository contains evaluation or design evidence, not a product contract. |
| `superseded` | A newer decision or artifact replaces this one. |
| `out_of_scope` | Another system owns the behavior. |

## Canonical set

Each concern has exactly one authority. The dated reviewed revision is recorded
in Traceability rather than copied into durable documents.

| Concern | Authority | Accountable owner | State | Review trigger |
|---|---|---|---|---|
| Product intent, users, scope, outcomes | [PRD](PRD.md) | Product owner | `accepted_architecture` | Product promise, user, scope, priority, or success target changes. |
| Functional and non-functional requirements | [TRD](TRD.md) | Runtime maintainers | `accepted_architecture` | API, runtime, dependency, NFR, security, or deployment behavior changes. |
| System boundaries and component ownership | [Architecture](../ARCHITECTURE.md) | Architecture owner | `accepted_architecture` | Component, trust boundary, integration, or failure domain changes. |
| Runtime interactions and state transitions | [UML](UML.md) | Architecture owner | `accepted_architecture` | Control flow, actor, state, or deployment topology changes. |
| Persisted, in-memory, external, and target data | [ERD](ERD.md) | Data owner | `accepted_architecture` | Object, relationship, retention, migration, or ownership changes. |
| Architecture decisions | [ADR index](adr/README.md) | Affected context owner | `accepted_architecture` | A durable choice, record status, or supersession condition changes; each ADR retains its own status. |
| Requirement-to-code-to-test mapping and dated audit | [Traceability](TRACEABILITY.md) | Release evidence owner | `active_pr` | Requirement status, protected revision, PR stack, or evidence changes. |
| Security abuse cases and controls | [Threat model](THREAT_MODEL.md) | Security owner | `accepted_architecture` | Asset, zone, threat, control, or residual risk changes. |
| Verification strategy and evidence taxonomy | [Test strategy](TEST_STRATEGY.md) | Quality owner | `accepted_architecture` | Test layer, coverage, review, or release gate changes. |
| Operations, degraded modes, recovery, and SLO entry criteria | [Operability](OPERABILITY.md) | Service owner | `accepted_architecture` | Dependency, signal, SLO, incident, recovery, or rollout changes. |
| Incident triage, containment, recovery, and evidence preservation | [Incident runbook](INCIDENT_RUNBOOK.md) | Incident commander | `accepted_architecture` | Severity, containment, recovery, or closure authority changes. |
| Release admission, build, migration, publication, rollback, and operational acceptance | [Release guide](RELEASE_GUIDE.md) | Release owner | `accepted_architecture` | Packaging, version, provenance, deployment, migration, rollback, or release evidence changes. |
| Primary research and authoritative standards | [References](REFERENCES.md) | Architecture owner | `research_only` | A cited primary source or governing standard changes. |
| Coordinated vulnerability disclosure | [Security policy](../SECURITY.md) | Security owner | `implemented_on_protected_main` | Reporting or response process changes. |

## Supporting evidence

The following remain useful supporting documents but do not replace the
canonical set:

- `conductor/` records context-driven development tracks.
- `docs/product_planning.md`, `docs/user_stories.md`, and
  `docs/rest_api_design.md` preserve earlier product-design inputs.
- `docs/architecture.md` is a research mapping for Fugu, Conductor, and
  TRINITY; root `ARCHITECTURE.md` is the current system authority.
- `docs/database_design.sql` is a reviewed production-target relational design,
  not the schema used by every protected-main runtime mode.
- `docs/commercial_*.md` are buyer-evidence packets and readiness views, not
  proof that external certifications, signatures, or production SLOs exist.
- `docs/papers/README.md` and `docs/REFERENCES.md` record research and standards.

## Change discipline

Behavior changes must update the affected canonical document, ADR, and
traceability row in the same pull request. A document may cite an active pull
request, but it must not describe that work as shipped. Volatile SHAs and run
IDs belong only in dated traceability evidence.
