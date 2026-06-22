# User Stories

## Platform Operator

- As a platform operator, I want to see all configured model agents and their current status so that I can detect provider degradation before users report failures.
- As a platform operator, I want to run a sample prompt through the active policy so that I can verify route versus conduct behavior before changing thresholds.

## AI Product Owner

- As an AI product owner, I want to inspect the workflow trace so that I can explain why a high-cost conducted workflow was used.
- As an AI product owner, I want policy thresholds to be visible so that quality-latency tradeoffs are reviewable.

## Compliance Reviewer

- As a compliance reviewer, I want access lists for every workflow step so that I can confirm agents only saw approved context.
- As a compliance reviewer, I want provider and data exclusions in the same screen as workflow traces so that audit decisions have runtime evidence.

## API Consumer

- As an API consumer, I want a single chat-completion compatible endpoint so that I can adopt orchestration without rewriting client code.
- As an API consumer, I want resource-oriented REST endpoints so that enterprise integrations can manage pools, policies, workflow runs, and locales.

## Localization Manager

- As a localization manager, I want locale bundles to be first-class API resources so that Korean and English UI changes can be reviewed independently from code.

