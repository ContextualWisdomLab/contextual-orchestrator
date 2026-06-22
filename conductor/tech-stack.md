# Technical Context

## Language

Python 3.11+.

## Dependencies

Runtime dependencies: none beyond the Python standard library.

Production target dependencies after this lab hardens:

- FastAPI for REST API, OpenAPI, typed request/response validation, and dependency injection.
- React-admin for the enterprise admin console.
- i18next for shared web i18n.
- PostgreSQL, SQLAlchemy, and Alembic for persistence and migrations.

## Interfaces

- CLI: `python -m contextual_orchestrator`
- HTTP: stdlib `/v1/chat/completions` subset
- Admin UI: static HTML/CSS/JS served by the stdlib HTTP server
- Worker protocol: OpenAI-compatible `POST /chat/completions`

## Architecture Style

DDD, kept minimal:

- Domain entities/value objects: `Agent`, `WorkflowStep`
- Application service: `Orchestrator`
- Infrastructure adapter: `ModelClient`
- Delivery adapter: `server.py`

## Rationale

The current goal is to encode architecture and workflow contracts, not provider-specific ergonomics. Add FastAPI, OpenAI SDKs, async workers, or persistent storage only after tests show the stdlib version is the bottleneck.
