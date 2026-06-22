# Code Conventions

## Object Naming

All configurable, API, and database object names must be lower snake_case with at least two semantic words.

Valid:

- `agent_pool`
- `workflow_run`
- `audit_event`
- `locale_bundle`
- `builder_agent`

Invalid:

- `agent`
- `workflow`
- `agentPool`
- `AgentPool`

Python class names keep Python convention but still use at least two semantic words, for example `ModelAgent`, `WorkflowStep`, `TaskOrchestrator`, and `ModelClient`.

Paper role values are deliberate exceptions because they are source terminology: `thinker`, `worker`, `verifier`, `synthesizer`.

## Enforcement

- `contextual_orchestrator.conventions.require_object_name()` validates configurable object identifiers.
- `tests/test_conventions.py` checks example agent ids and naming helpers.
- DB DDL in `docs/database_design.sql` follows the same rule.

## Module Rules

- Domain code stays in `contextual_orchestrator/orchestrator.py` until a second implementation forces extraction.
- Delivery adapters live in `server.py`.
- UI static assets live in `admin.py` only while the product remains dependency-free.
- Do not introduce provider SDKs unless OpenAI-compatible HTTP falls short.

