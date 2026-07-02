# Commercial Launch Readiness

Commercial launch readiness is the KRW 2,000,000,000 launch/trial execution gate for Contextual Orchestrator. It packages the repo-local go-to-market packet, runtime path, acceptance tests, operator runbook, admin evidence, analytics truthfulness, Figma artifacts, review-process policy, and packaging decision into `/api/v1/commercial_launch_readiness/latest`.

It does not certify a completed sale. It separates launchable repository evidence from buyer environment, production telemetry, and commercial signature inputs that must come from the buyer or production deployment.

Figma Code Connect is not used.

Review process is not a blocker unless it reports a concrete product, security, API-contract, or document defect.

Do not create a separate library, Git submodule, or extracted package now. The launch packet remains one deployable enterprise control-plane product until a second product, independent release cadence, or provenance requirement exists.

## Launch Inputs

| Input | Source | Evidence type | Launch handling |
|---|---|---|---|
| Go-to-market packet | `/api/v1/commercial_go_to_market_readiness/latest`, `docs/commercial_go_to_market_readiness.md` | repository_and_runtime_artifact | Ready when GTM is not blocked. |
| Runtime launch path | `README.md`, `contextual_orchestrator/server.py`, `docs/rest_api_design.md`, `/v1/chat/completions`, `/admin` | repository_artifact | Ready when the stdlib server, admin console, and API contract are present. |
| Acceptance test packet | `/api/v1/commercial_acceptance_checks/latest`, focused tests, `pytest -q` | measured_local | Ready when acceptance is not blocked and local verification files exist. |
| Operator runbook packet | `/api/v1/commercial_operations_readiness/latest`, `/api/v1/commercial_onboarding_readiness/latest` | repository_and_runtime_artifact | Ready when operations and onboarding packets are not blocked. |
| Admin observability packet | `/admin`, `/admin/state`, `docs/screen_design.md` | repository_and_runtime_artifact | Ready when existing admin evidence surface is present. |
| Buyer environment inputs | buyer URL, topology, credential handoff, retention, network policy | buyer_environment_required | Warning until buyer provides or waives inputs. |
| Production telemetry inputs | production logs, SLOs, incident drill, backup restore proof | proposed_until_production | Warning until production telemetry exists. |
| Commercial signature inputs | signed order/MSA, DPA/security acceptance, PO, go-live authorization | buyer_signature_required | Warning until buyer signatures or waivers exist. |

## Runtime Shape

`commercial_launch_readiness_report()` returns:

- `launch_status`: `commercial_launch_ready`, `commercial_launch_ready_with_warnings`, or `commercial_launch_blocked`.
- `measurement_status`: `local_commercial_launch_readiness`.
- `launch_summary`: ready, warning, blocked, external input, buyer environment, production telemetry, commercial signature, and review-process counts.
- `launch_items`: evidence rows with owner, sources, evidence type, completion state, action, and exit criteria.
- `related_runtime_reports`: GTM, operations, onboarding, acceptance, and analytics status links.
- `review_process_policy`: review delay is not a blocker without a concrete failure.
- `library_split_decision`: keep one product.
- `launch_links`: Figma design file, FigJam board, runtime endpoint, and this document.

## Launch Status Rules

- `commercial_launch_ready`: GTM, runtime, acceptance, operator, admin, buyer environment, production telemetry, commercial signature, review policy, and packaging evidence are ready.
- `commercial_launch_ready_with_warnings`: repo-local launch packet is ready while buyer environment, production telemetry, or commercial signature inputs remain explicit warnings.
- `commercial_launch_blocked`: missing local launch packet evidence, concrete product defect, API contract failure, document mismatch, security failure, or Code Connect usage blocks launch readiness.

## Analytics Guardrail

`commercial_launch_external_input_count` counts buyer-environment, production-telemetry, and commercial-signature input groups. It is `proposed_until_buyer_specific` because those values cannot be measured honestly from this repository alone.

## Figma Artifact

The FigJam diagram name is `KRW 2B Commercial Launch Readiness`. It maps GTM, operations, onboarding, acceptance, analytics, admin, review policy, and single-product packaging into the launch packet, then separates buyer environment, production telemetry, and commercial signature warnings from concrete blockers.
