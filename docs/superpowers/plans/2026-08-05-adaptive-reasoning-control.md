# Adaptive Reasoning Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans task by task. Every behavior change follows red-green-refactor.

**Goal:** Add explicit role-aware provider reasoning control, bounded verification escalation, and ablation without weakening routing, fallback, or provider-egress security.

**Architecture:** Use focused stdlib modules behind `reasoning_control` and `reasoning_runtime` facades. Integrate through idempotent hooks on stable agent, client, orchestrator, and policy seams. Store capability by object identity and decisions in request-local contexts.

**Tech Stack:** Python 3.10+, stdlib dataclasses, `ContextVar`, `weakref`, JSON, pytest, coverage.py.

## Global Constraints

- No new runtime dependency.
- No model-name capability inference.
- No provider secret from argv or runtime environment fallback.
- No caller-owned reasoning-field overwrite.
- No private intermediate reasoning persistence.
- Maximum one verifier-driven escalation.
- New database object names, if any, must be two-or-more-word `snake_case`.
- New production statement, branch, and docstring coverage must be 100%.
- Stack order: #96 → #94 → adaptive reasoning control.

---

### Task 1: Capability profiles and payload rules

**Files:** `_reasoning_profile.py`, `_reasoning_payload.py`, `reasoning_control.py`, control tests.

- [x] Write failing tests for invalid presets, level ordering, unsafe paths, incomplete mappings, caller-owned fields, nested conflicts, and OpenAI/NVIDIA/Nemotron/Gemini/custom projections.
- [x] Verify failures are caused by missing behavior.
- [x] Implement immutable profiles, strict rules, endpoint normalization, fixed templates, and usage-token extraction.
- [x] Run focused tests and preserve 100% statement/branch coverage.

### Task 2: Role-aware decision policy

**Files:** `_reasoning_policy.py`, control tests.

- [x] Write failing tests for disabled, fixed, adaptive, long-context, multi-step, multiple-complexity, multiple-high-impact, cap, failover projection, and next-level escalation behavior.
- [x] Implement canonical levels and least-cost bounded selection.
- [x] Verify fixed cells and decision serialization.

### Task 3: Request-local runtime state

**Files:** `_reasoning_state.py`, `reasoning_runtime.py`, runtime tests.

- [x] Write failing tests proving equality-identical frozen dataclasses do not share profiles.
- [x] Implement weak identity registries and context-local decision/policy/override/event state.
- [x] Verify context cleanup and stale weak-reference branches.

### Task 4: Provider-client integration

**Files:** `_reasoning_client_hooks.py`, `_reasoning_workflow.py`, runtime tests.

- [x] Write failing tests for chat, streaming, raw chat, Responses, per-item Batch decisions, and secured-upload rewriting.
- [x] Implement endpoint-specific projection and trace events.
- [x] Verify unprofiled models retain legacy payloads and caller settings win.

### Task 5: Orchestrator integration and realistic recovery

**Files:** `_reasoning_orchestrator_hooks.py`, runtime tests.

- [x] Write a realistic failing test where low effort returns `41`, verification rejects it, medium returns `42`, and synthesis recovers the correct answer.
- [x] Implement route/conduct capture, generated planner and model-judge role decisions, one worker escalation, and downstream recomputation.
- [x] Add fixed-effort ablation and reasoning-token totals.
- [x] Verify lower effort uses fewer reasoning tokens while the bounded retry recovers correctness.

### Task 6: Governance, persistence, documentation, and packaging

**Files:** `__init__.py`, admin/persistence hooks, architecture, library research, doctoring, subsystem guide, CHANGELOG.

- [x] Write a failing regression test proving frozen-agent replacement drops profile capability without a transfer hook.
- [x] Preserve or explicitly update profiles across agent patching, expose them in admin data, and re-save through the pool store.
- [x] Add APA 7 research and standards traceability.
- [x] Verify 100% statement/branch/docstring coverage and compile all new modules.
- [ ] Run full repository checks on the published exact head.
- [ ] Obtain independent exact-head approval and merge only after ancestor PRs integrate.
