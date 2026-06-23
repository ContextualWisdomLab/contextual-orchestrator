# Product Planning Reboot

## Goal

Re-plan Contextual Orchestrator as an enterprise orchestration control plane, not as a generic multi-agent demo. The product should preserve the Fugu-style adoption promise of one model-like API while giving operators the evidence they need to manage model pools, latency-quality tradeoffs, workflow visibility, access control, and compliance constraints.

## Sources Re-read

| Source | Product Signal |
|---|---|
| Sakana Fugu launch article, June 22, 2026 | One API hides model selection, delegation, verification, and synthesis. Fugu is the everyday low-latency mode; Fugu Ultra is the high-quality deep-workflow mode. Early user value clusters around code review, security analysis, research, and long messy workflows. |
| Sakana Fugu Technical Report, 2026 | The product must expose a single model interface, a configurable worker pool, provider preference/exclusion, privacy and compliance constraints, and the latency-quality frontier. |
| TRINITY: An Evolved LLM Coordinator, ICLR 2026 | The operator-facing trace should show Thinker, Worker, and Verifier contracts, turn budgets, and why verification accepted or revised the accumulated answer. |
| Learning to Orchestrate Agents in Natural Language with the Conductor, ICLR 2026 | Workflow runs should be represented as natural-language subtasks, assigned workers, and access lists. Harder tasks should visibly allocate more work than simple tasks. |

## Product Thesis

Enterprise teams want the benefit of collective model intelligence without making every application team design, debug, and govern multi-agent workflows. Contextual Orchestrator should therefore be a control plane with one compatible inference API and one management console that explains what happened inside the orchestration layer.

## Primary Product Bets

1. Single API compatibility is the adoption wedge. API consumers should keep calling `/v1/chat/completions`.
2. The agent pool is a managed enterprise asset. Operators need provider, model, capability, priority, health, and exclusion metadata in one place.
3. Fast versus deep orchestration is a workload policy decision. Product UI should expose latency budgets, deep-workflow triggers, and mode overrides.
4. Traceability is the core enterprise differentiator. Every workflow run needs role, subtask, worker, access list, verifier outcome, and final synthesis evidence.
5. Compliance is runtime evidence, not a static checkbox. Provider exclusions and access-list exposure should sit next to the run that used them.
6. i18n is part of operability. English and Korean labels should ship as first-class locale bundles because global platform and compliance teams review the same evidence.

## Personas And Jobs

| Persona | Job To Be Done |
|---|---|
| Platform operator | Keep the model pool healthy, exclude degraded or disallowed providers, and verify policy changes before users feel them. |
| AI product owner | Explain why a request used fast routing or deep orchestration, and tune the latency-quality threshold for a product surface. |
| Compliance reviewer | Prove which worker saw which context, which providers were excluded, and whether the final answer passed verification. |
| API application owner | Adopt orchestration behind an OpenAI-compatible endpoint without rewriting client code. |
| Localization owner | Review Korean and English operator copy without changing application code. |

## MVP Surfaces

| Surface | Why It Exists |
|---|---|
| Admin dashboard | Fugu says the user should see one model; enterprise operators still need internal evidence. |
| Agent pool | Fugu report makes pool configurability and provider exclusion first-class. |
| Orchestration policy | Fugu and Fugu Ultra define the latency-quality frontier that operators must tune. |
| Workflow run trace | TRINITY and Conductor both make role/step behavior central to coordination quality. |
| Access list inspector | Conductor access lists are the concrete mechanism for context visibility and auditability. |
| Evaluation replay | TRINITY and Fugu both optimize against measured task outcomes; product teams need replay before learned routing exists. |
| Locale bundle editor | i18n support is an explicit product requirement and should be reviewable as data. |

## Deliberate Non-goals For This Repository

- No learned coordinator training. Keep deterministic routing until there is an evaluation set proving it is the bottleneck.
- No visual workflow builder. Tables and trace details are enough until operators need to author complex topologies.
- No recursive topology UI. Conductor recursion is a future scaling knob, not an MVP control.
- No billing, SSO, or RBAC implementation in the stdlib lab. Document the need; add it with the enterprise stack.

## Acceptance Criteria

- Product planning, screen design, user stories, and API design all cite paper-backed requirements.
- The management console prioritizes traceability and policy control over decorative SaaS chrome.
- Every new product surface maps to one of: single API adoption, pool management, policy control, trace audit, access-list evidence, evaluation replay, or i18n.
