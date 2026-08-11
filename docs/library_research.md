# Library Research and Adoption Status

This record compares library candidates with the code that is actually shipped
on protected `main`. Status labels use the canonical vocabulary: an optional
dependency is not an implemented integration, and a design choice is not
presented as production behavior merely because its package is installable.

## Selected Stack

| Area | Status | Current decision | Evidence |
|---|---|---|---|
| HTTP runtime | `implemented_on_protected_main` | The production path uses `ThreadingHTTPServer` with bounded request handling. | `contextual_orchestrator/server.py` constructs the server and handler directly. |
| API framework | `planned` | FastAPI and Uvicorn remain candidates. The optional `api` extra makes them installable, but production request dispatch does not dispatch through FastAPI. | `pyproject.toml` declares the extra; production modules do not import FastAPI or Uvicorn. |
| API contract | `implemented_on_protected_main` | Keep the handwritten OpenAPI 3.1 contract synchronized with runtime dispatch. | `contextual_orchestrator/api_contract.py` and contract tests verify the current routes. |
| Admin console | `implemented_on_protected_main` / `planned` | The static admin UI is current. React-admin remains a planned replacement only if CRUD and external identity integration justify it. | `contextual_orchestrator/admin.py`; React-admin is not a runtime dependency. |
| Internationalization | `implemented_on_protected_main` / `planned` | Current English/Korean resources are inlined. i18next remains planned for a separately built web client. | Admin locale tests cover the current bundle; i18next is not installed. |
| Persistence | `implemented_on_protected_main` / `accepted_architecture` | Current code supports SQLite state, a PEP-249 ledger, and optional direct `psycopg` credential storage. SQLAlchemy ORM and Alembic remain accepted architecture, not current runtime behavior. | The optional `db` extra installs SQLAlchemy, Alembic, and psycopg, but production code does not use SQLAlchemy ORM or Alembic migrations. |
| Database model | `implemented_on_protected_main` / `accepted_architecture` | Runtime adapters use SQLite or PostgreSQL-compatible paths; the normalized model in `docs/database_design.sql` remains an accepted migration target. | `docs/ERD.md` distinguishes runtime, external, conceptual, and planned entities. |

## Dependency-Adoption Rule

No new dependency is added until it carries real product weight:

- Current implementation: stdlib `ThreadingHTTPServer`, handwritten OpenAPI,
  static admin UI, inlined locales, SQLite/PEP-249 state paths, and an optional
  direct-psycopg credential backend.
- Optional extras advertise installable compatibility surfaces. They do not
  prove that FastAPI, SQLAlchemy ORM, or Alembic owns a production call path.
- Adopt FastAPI, React-admin, i18next, SQLAlchemy, or Alembic only with a bounded
  product requirement, migration and rollback evidence, and tests proving the
  new authority boundary.
- Do not add provider SDKs until raw OpenAI-compatible HTTP is insufficient.

Skipped: custom admin framework, custom i18n engine, custom migration engine.

## Commercial Packaging Decision

For the KRW 2,000,000,000 commercial-readiness plan, keep Contextual
Orchestrator as one repository and one deployable product. Do not split the
orchestration core into a separate library, Git submodule, or package yet.

Reason:

- The buyer value is the integrated system: compatible API, admin evidence
  surface, workflow trace, access-list reports, analytics snapshot, sales
  readiness, and commercial readiness.
- A separate library would create release, versioning, and support overhead
  before there is an external SDK consumer or independent orchestration-core
  release cadence.
- A Git submodule would make due-diligence review harder because buyers need a
  single evidence packet, not a multi-repo dependency chain.

Extraction triggers:

- A second product or external customer needs the orchestration engine without
  the admin control plane.
- The orchestration core needs a separately versioned API and compatibility
  matrix.
- Security review requires a reusable, locked core package with independent
  provenance.

Until those triggers exist, the accepted architecture is to strengthen the
current single-repository product instead of splitting it.

## Required For New Designs

Every new subsystem design must update this file before implementation starts. The entry must name the existing libraries researched, the selected library or stdlib alternative, and the custom code that was deliberately skipped.
