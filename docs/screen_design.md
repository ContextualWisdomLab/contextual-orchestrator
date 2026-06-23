# Screen Design

## Design Source

The management console is grounded in the papers, not only in generic SaaS admin patterns. The screen exists because the public product shape is intentionally simple: one API hides the orchestration. Enterprise users therefore need an internal evidence surface that explains the hidden routing, delegation, verification, synthesis, provider exclusion, and context visibility decisions.

See [product planning](product_planning.md) for the source-backed product thesis.

## Paper-to-screen Traceability

| Screen Area | Paper Basis | Product Reason |
|---|---|---|
| Agent Pool table | Fugu report: configurable worker pool, provider preference, exclusion, privacy/compliance constraints. | Operators must see which workers exist, whether a provider is degraded, and which capabilities each worker advertises. |
| Orchestration Policy panel | Fugu report: latency-aware Fugu versus quality-oriented Fugu-Ultra. | Operators need visible thresholds that decide route versus conduct behavior. |
| Workflow Run Trace | TRINITY: multi-turn coordinator with Thinker, Worker, Verifier roles. Conductor: workflow steps. | Operators need to audit why the system delegated and which role each agent played. |
| Access List Inspector | Conductor: each step includes an access list of previous step outputs. Fugu-Ultra: intra-workflow isolation with shared memory across turns. | Operators need proof that workers only saw allowed prior context. |
| Evaluation Replay | TRINITY and Fugu optimize routing decisions against measured task outcomes. | Product owners need a way to replay prompts before replacing heuristic routing with learned coordination. |
| Audit & Compliance | Fugu report: pools can exclude providers or respect privacy/compliance constraints without retraining. | Enterprise users need policy evidence and recent exceptions next to runtime behavior. |
| i18n language selector | User requirement. | Global admin teams need English and Korean UI from the first version. |

## Primary User Flows

1. Operations admin opens `/admin`, checks health, and scans degraded agents.
2. Platform owner adjusts orchestration policy thresholds after reviewing live trace behavior.
3. Compliance reviewer opens a workflow run and checks access-list exposure and exclusions.
4. AI product owner replays a prompt to compare fast route and deep workflow behavior before policy rollout.
5. Support engineer simulates a prompt and copies the trace JSON for incident review.

## Design Tokens

- Background: `#f7f8f7`
- Surface: `#ffffff`
- Border: `#dfe5e3`
- Text: `#1c2524`
- Muted text: `#62706d`
- Primary accent: `#087f7a`
- Warning accent: `#b96f00`
- Radius: `6px`
- Component density: enterprise table-first, no nested cards

## Accessibility Baseline

- Native buttons, inputs, tables, and select controls.
- Landmark navigation with `nav` and `main`.
- Visible text labels for operational fields.
- Minimum interactive height: 34px now; production React-admin target should move primary controls to 44px where touch operation matters.
- Dynamic simulation should announce completion through a live region in the next UI pass.
