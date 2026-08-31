# Technical Context

## Language

Python 3.11+.

## Dependencies

Runtime dependencies:

- `cryptography` for AES-256-GCM protection of explicitly marked PII fields.
- `opentelemetry-api`/`-sdk`/`-exporter-otlp-proto-http` for optional request-correlation tracing (ADR 0122; disabled unless an OTLP endpoint is configured).
- `jsonschema` for structured-output validation against caller-supplied schemas.
- The HTTP server, persistence, orchestration core, and verbose/debug logging (`debug_logging.py`, ADR 0005) remain Python standard-library based.

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

- Domain entities/value objects: `ModelAgent`, `WorkflowStep`
- Application service: `TaskOrchestrator`
- Infrastructure adapter: `ModelClient`
- Delivery adapter: `server.py`

## Rationale

The current goal is to encode architecture and workflow contracts, not provider-specific ergonomics. Add FastAPI, OpenAI SDKs, async workers, or persistent storage only after tests show the stdlib version is the bottleneck.
