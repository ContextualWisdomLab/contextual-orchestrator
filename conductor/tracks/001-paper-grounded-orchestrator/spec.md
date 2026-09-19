# Spec: Paper-Grounded Orchestrator

## Acceptance Criteria

- The public API accepts chat messages through one OpenAI-compatible endpoint.
- Simple prompts use one selected worker.
- Complex prompts use a workflow with thinker, worker, verifier, and synthesizer steps.
- Workflow steps expose only the prior outputs listed in their access list.
- Operators can open a management console to inspect agent pool, policy, trace, and audit state.
- Tests encode the Fugu, TRINITY, and Conductor contracts.
- Architecture documentation cites the launch article, technical report, and related papers.
- Library research identifies FastAPI, React-admin, i18next, SQLAlchemy, Alembic, PostgreSQL, and OpenAPI as production targets.
