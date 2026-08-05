# Library Research

The design researched existing libraries and provider contracts before adding code. The repository keeps the runtime dependency-free for the current lab, but the enterprise implementation target is explicit.

## Selected Stack

| Area | Library or contract | Decision | Evidence |
|---|---|---|---|
| REST API | [FastAPI](https://github.com/fastapi/fastapi) | Use when the API moves beyond the current stdlib prototype. | FastAPI provides Pydantic validation, response declarations, and OpenAPI/JSON Schema generation. Context7: `/fastapi/fastapi`. |
| Admin console | [React-admin](https://github.com/marmelab/react-admin) | Use for production CRUD/admin surfaces. | React-admin provides resource, data-provider, authentication, i18n, dashboard, layout, and route extension points. Context7: `/marmelab/react-admin`. |
| i18n | [i18next](https://github.com/i18next/i18next) | Use for shared web translation runtime. | i18next supports resource bundles, fallback languages, interpolation, detection, and runtime language changes. Context7: `/i18next/i18next`. |
| Persistence | [SQLAlchemy 2.x](https://docs.sqlalchemy.org/orm/) | Use for Python domain persistence. | Official docs cover mapped classes, sessions, and transaction patterns. |
| Migrations | [Alembic](https://alembic.sqlalchemy.org/) | Use for schema migration lifecycle. | Alembic supports versioned SQLAlchemy migrations and metadata comparison. |
| Database | [PostgreSQL](https://www.postgresql.org/docs/current/sql-syntax-lexical.html) | Default relational store. | The project standardizes new objects on unquoted lower two-or-more-word `snake_case`. |
| API contract | [OpenAPI 3.1](https://spec.openapis.org/oas/v3.1.0.html) | Contract format for review and client generation. | OAS is a language-agnostic HTTP API description for humans and machines. |
| Reasoning control | Official OpenAI, NVIDIA NIM, and Gemini contracts | Use explicit profiles and stdlib JSON projection; do not add provider SDKs. | Providers expose different effort sets, thinking toggles, budgets, nesting, and endpoint support. |
| Orchestration research | Fugu, Conductor, TRINITY, RouteLLM, FrugalGPT, test-time-compute scaling | Preserve three independent compute axes and measure their trade-offs. | The papers support learned routing/topology, role assignment, recursive scaling, cost-aware routing, and task-dependent compute allocation. |
| AI governance | ISO/IEC 23894:2023; ISO/IEC 42001:2023 | Record policy, capability, decision, override, escalation, usage, and ablation evidence. | The standards support risk-management integration and an organization-level AI management system. |

## Reasoning-Control Decision

No new runtime dependency is required. A provider SDK would make the core less portable and would not solve the model-dependent capability problem. The selected design uses:

- immutable Python dataclasses for validated profiles and decisions;
- `ContextVar` for request-local canonical decisions and bounded overrides;
- explicit nested JSON rules for provider payload mapping;
- weak identity registries so frozen value objects do not collide by equality;
- an idempotent runtime installer so standalone core use remains possible;
- existing pinned HTTPS and KV credential seams for provider calls.

Deliberately skipped:

- model-name parsing or hard-coded authoritative model inventories;
- arbitrary dictionaries copied into provider requests;
- expression languages for payload mutation;
- provider SDK dependencies;
- hidden reasoning-text persistence;
- an unbounded “retry until accepted” loop;
- a learned effort router before sufficient task-level evaluation evidence exists.

## Ponytail Decision

No new dependency is added until it carries real product weight:

- Current prototype: stdlib server, handwritten OpenAPI, static admin UI, stdlib reasoning-control extension.
- First enterprise cut: FastAPI + React-admin + i18next + PostgreSQL + SQLAlchemy + Alembic.
- Do not add provider SDKs until raw OpenAI-compatible HTTP and validated custom mappings are demonstrably insufficient.

Skipped: custom admin framework, custom i18n engine, custom migration engine, and duplicated provider clients.

## Commercial Packaging Decision

For the commercial-readiness plan, keep Contextual Orchestrator as one repository and one deployable product. Do not split the orchestration core into a separate library, Git submodule, or package yet.

Reason:

- Buyer value is the integrated compatible API, routing, reasoning controls, admin evidence, workflow trace, access reports, analytics, and governance boundary.
- A separate library would add release, versioning, and support overhead before an external SDK consumer or independent core cadence exists.
- A Git submodule would make due-diligence review harder because buyers need one evidence packet rather than a multi-repository dependency chain.

Extraction triggers:

- A second product or external customer needs the engine without the admin control plane.
- The core needs a separately versioned API and compatibility matrix.
- Security review requires a reusable locked package with independent provenance.

Until those triggers exist, strengthen the single-repository product while retaining focused, importable modules.

## Required For New Designs

Every new subsystem design must update this file before implementation. The entry must name the libraries, standards, papers, or official provider contracts researched; the selected library or stdlib alternative; and the custom code deliberately skipped.
