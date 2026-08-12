# Technical Context

## Language

Python 3.11+.

## Current implementation dependencies

The current Python HTTP and control path uses the standard library. Project
metadata also declares optional `api` and `db` extras. Those optional extras are
installable compatibility surfaces, not proof of an implemented framework or
ORM integration.

## Planned adoption candidates

- FastAPI for a future typed REST adapter when its migration triggers are met.
- React-admin for a separately built enterprise admin client.
- i18next for shared web internationalization.
- SQLAlchemy and Alembic for a future normalized persistence layer. Current
  code uses SQLite/PEP-249 state paths and an optional direct-psycopg credential
  backend.

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

Adopt FastAPI, provider SDKs, async workers, or an ORM only after a bounded
product requirement, migration and rollback evidence, and tests prove the new
authority boundary.
