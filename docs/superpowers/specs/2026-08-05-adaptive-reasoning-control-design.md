# Adaptive Reasoning Control Design

## Goal

Add an explicit provider-neutral reasoning-compute layer that lowers expected cost while preserving difficult-task capability, standalone operation, and modular CWL MSA use.

## Evidence and problem statement

The repository already allocates test-time compute through model routing and workflow topology. Fugu, Conductor, and TRINITY support adaptive model/role/topology coordination, while test-time-compute and cost-aware routing research supports allocating compute by task evidence rather than using one maximum setting. Current provider APIs expose incompatible effort names, thinking toggles, budgets, and nesting. A single forwarded vendor field cannot control internal planner, worker, verifier, synthesizer, failover, streaming, Responses, and Batch calls.

## Considered approaches

### Infer support from model names

Rejected. Aliases and provider behavior change; unsupported parameters fail requests; hidden inference is not auditable.

### Forward caller fields only

Rejected. This preserves expert control but does not optimize internal orchestration calls.

### Explicit profiles plus bounded adaptive escalation

Selected. Each agent declares supported levels and endpoint mappings. The runtime chooses a canonical decision, projects it onto a candidate's declared capability, preserves caller-owned fields, and permits one next-level worker retry after verifier rejection.

## Architecture

Focused modules keep responsibilities independently testable:

- `_reasoning_profile.py`: validated capability profiles and payload rules;
- `_reasoning_policy.py`: adaptive/fixed selection, failover projection, escalation, and ablation value objects;
- `_reasoning_payload.py`: endpoint mapping and usage-token accounting;
- `reasoning_control.py`: public control facade;
- `_reasoning_state.py`: weak identity registries and request-local contexts;
- `_reasoning_workflow.py`: trace annotation, Batch JSONL projection, and downstream retry recomputation;
- `_reasoning_config_hooks.py`: agent round-trip and policy snapshot integration;
- `_reasoning_client_hooks.py`: chat, stream, passthrough, and Batch provider hooks;
- `_reasoning_orchestrator_hooks.py`: role invocation, admin visibility, replacement preservation, traces, retry, and ablation;
- `reasoning_runtime.py`: side-effect-free explicit activation and idempotent typed installation.

No new runtime dependency is introduced.

## Activation decision

Importing the public package must not install optional reasoning hooks or mutate core classes. The package exports `enable_reasoning_control()` as an explicit composition-root action. The built-in CLI calls it before loading agent configuration; library and MSA consumers call it before creating runtime objects only when they need adaptive reasoning.

Repeated activation is idempotent. Isolated alternate runtimes and test fakes may call the lower-level typed installer with their own class set. This preserves the extension's current implementation seams while preventing global import-order dependence and gives a stable public boundary for a future composition- or subclass-based implementation.

## Data flow

1. Explicitly activate the reasoning extension at the application composition root.
2. Resolve the selected agent's explicit profile.
3. Select a canonical level from policy, role, and bounded task signals.
4. Project the level to the candidate model during failover.
5. Enter a request-local decision scope.
6. Add endpoint-specific fields only when the caller does not own the complete path.
7. Call the provider through the existing pinned HTTPS and KV credential seams.
8. Capture usage and trace-safe decision evidence.
9. If verification rejects the worker, retry once at the next supported level and recompute affected downstream roles.

## Compatibility and persistence

- Importing `contextual_orchestrator` alone leaves reasoning hooks inactive.
- The product CLI activates reasoning before loading agent files.
- An unprofiled agent preserves legacy request shape after activation.
- Agent configuration round-trips `reasoning_profile`.
- Admin list/add/patch surfaces expose profile capability.
- Frozen-dataclass replacement preserves the prior profile unless an explicit profile patch changes or removes it.
- Durable agent-pool storage re-saves the replacement after the profile is attached.
- Caller payloads, provider retries, circuit breakers, route/conduct decisions, and security transport remain authoritative.

## Security and privacy

- No model-name inference or authoritative hard-coded inventory.
- No arbitrary payload dictionaries or expression evaluation.
- Safe path segments, bounded depth, JSON-scalar values, and strict templates only.
- Caller-owned complete paths are not overwritten, including explicit `null`.
- Hidden reasoning content is not stored; only level, factors, role, cap, escalation index, and token counts are recorded.
- Existing DNS pinning, SNI/certificate verification, proxy bypass, redirect rejection, and KV secret resolution remain unchanged.
- Optional reasoning activation is explicit rather than an import-time global mutation.

## Testing and acceptance

Tests must cover malformed profiles, provider presets, custom paths, caller ownership, adaptive/fixed policies, high-impact thresholds, failover projection, route/conduct, planner, verifier, streaming, Responses passthrough, Batch JSONL, admin visibility, durable profile re-save, bounded escalation, realistic arithmetic recovery, fixed-effort ablation, import purity, and idempotent explicit activation.

Acceptance requires:

- 100% statement coverage for every new production module;
- 100% branch coverage for every new production module;
- complete production and nested-function docstrings;
- package compile/import smoke tests;
- exact-head repository Tests, Fuzz, Security, Security Scan, SAST, package build/install, and independent review;
- no merge before stack ancestors are integrated.

## Stack and release

The development stack is security PR #96, then free-first fallback PR #94, then this reasoning-control PR. The feature PR remains Draft until ancestors merge and it is rebased or retargeted to the integrated exact base. The package remains `0.1.0`; no tag or release is authorized by this feature alone.
