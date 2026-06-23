# User Stories

## Source Basis

These stories are derived from the product planning reboot, not from generic admin-console assumptions:

- Fugu: single API, latency-quality modes, configurable agent pool, provider exclusion, privacy/compliance constraints.
- TRINITY: Thinker, Worker, Verifier role contracts and explicit verification acceptance.
- Conductor: natural-language workflow steps, worker assignment, and access-list controlled context.

## Platform Operator

- As a platform operator, I want to see all configured model agents and their current status so that I can detect provider degradation before users report failures.
- As a platform operator, I want to run a sample prompt through the active policy so that I can verify route versus conduct behavior before changing thresholds.
- As a platform operator, I want to mark a provider or model as excluded so that restricted workloads do not route to it.

## AI Product Owner

- As an AI product owner, I want to inspect the workflow trace so that I can explain why a high-cost conducted workflow was used.
- As an AI product owner, I want policy thresholds to be visible so that quality-latency tradeoffs are reviewable.
- As an AI product owner, I want replay results for a prompt so that I can compare fast routing with deeper orchestration before changing product defaults.

## Compliance Reviewer

- As a compliance reviewer, I want access lists for every workflow step so that I can confirm agents only saw approved context.
- As a compliance reviewer, I want provider and data exclusions in the same screen as workflow traces so that audit decisions have runtime evidence.
- As a compliance reviewer, I want verifier decisions and final synthesis evidence so that I can review whether the answer was accepted for a defensible reason.

## API Consumer

- As an API consumer, I want a single chat-completion compatible endpoint so that I can adopt orchestration without rewriting client code.
- As an API consumer, I want resource-oriented REST endpoints so that enterprise integrations can manage pools, policies, workflow runs, and locales.

## Localization Manager

- As a localization manager, I want locale bundles to be first-class API resources so that Korean and English UI changes can be reviewed independently from code.

## Backlog Stories

- As a platform operator, I want SSO and RBAC so that only authorized operators can change routing policy.
- As an AI researcher, I want evaluation datasets and success metrics so that learned routing can replace heuristics only when it proves better.
- As an advanced operator, I want recursive workflow controls so that expensive test-time scaling can be enabled only for approved workloads.
