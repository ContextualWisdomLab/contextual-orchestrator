# ADR-0012: Standalone product and explicit CWL boundary

## Status

`implemented_on_protected_main`

## Context and decision drivers

Contextual Orchestrator is both an independently useful service/library and a
module in the ContextualWisdomLab ecosystem. Hidden dependence on a central
control plane would break offline tests, local adoption, failure isolation, and
ownership clarity; duplicating host identity or business data would create a
conflicting authority.

## Considered alternatives

- require the full CWL stack: integrated but not independently deployable;
- copy identity, tenancy, and business records into this service: convenient
  locally but creates ownership and synchronization conflicts;
- expose only a library with no service boundary: limits compatible adoption;
- keep standalone defaults and add explicit, optional host/adaptor contracts:
  selected.

## Decision

The core runs offline with mock agents and in memory, and can run as a compatible
HTTP service with configured providers. Optional SQLite, SQL/KV,
`pg-llm-batch`, Clearfolio, naruon, inkspan, and other CWL integrations enter
through explicit interfaces. The host owns ingress identity, tenant/purpose
authorization, business records, deployment, and end-user privacy unless a
versioned contract delegates a specific responsibility.

## Consequences

Basic operation stays dependency-light and testable. Integrations must translate
and authorize at their boundary rather than importing implicit global state.

## Failure and recovery

An optional CWL dependency outage degrades only its declared capability. The
standalone route/library path remains available when safe. Recovery revalidates
the adapter contract and never backfills fabricated evidence.

## Security, privacy, and governance impact

Authority and data ownership remain local to the system that has purpose and
tenant context. A viewer, batch service, or orchestrator response does not grant
host access or merge/release authority.

## Compatibility and migration

Adapters are optional and versioned. Breaking a host boundary requires staged
dual compatibility, ownership reconciliation, and coordinated rollback.

## Verification and acceptance

Offline install/import/mock tests run without CWL dependencies. Contract tests
cover each adapter, missing/degraded dependency behavior, data minimization,
authorization handoff, and independent startup/recovery.

## Rollback and supersession

Disable the adapter and retain standalone behavior. Supersession must preserve
an independent mode or explicitly reclassify the product with migration,
availability, and ownership evidence.

## References

NIST SP 800-218 and ISO/IEC 42001:2023. See
[the reference index](../REFERENCES.md).
