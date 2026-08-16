# Database Conventions

## Naming

- Every database object name uses lower snake_case.
- Every table, enum, index, constraint, and column name has at least two words.
- Do not use quoted identifiers.
- Primary key columns are resource-specific: `agent_id`, `workflow_run_id`, `audit_event_id`.
- Foreign keys keep the referenced resource name: `workflow_run_id`, `policy_id`.
- Timestamps are `created_at`, `updated_at`, or domain-specific two-word names such as `started_at`.

## Migrations

- Alembic is the production migration tool.
- Every migration has upgrade and downgrade paths.
- Breaking changes use expand/backfill/contract phases.
- Large data changes are batched and monitored.

## Meaning-unit embeddings (3NF)

These objects are the persistence target when a buyer stores meaning-unit
vectors (naruon import, Clearfolio attachment search). They are not required
for the in-memory batch path.

| Object | Keys | Purpose |
|---|---|---|
| `source_document` | `document_id`, `account_id`, `received_at`, `media_type` | One imported email, HTML body, or file. |
| `meaning_unit` | `unit_id`, `document_id`, `input_index`, `chunk_index`, `chunk_kind`, `source_offset`, `source_length`, `chunk_text` | One retrieval grain. `chunk_text` equals the source slice. |
| `unit_embedding` | `unit_id`, `model_name`, `embedding_vector`, `prompt_tokens` | One vector per unit per model. Not stored on `meaning_unit` (3NF). |
| `embedded_image` | `image_id`, `document_id`, `source_offset`, `source_length`, `media_type` | Position of a `data:image` span. OCR text and object tags belong on child tables, not here. |
| `image_text_span` | `image_id`, `span_index`, `ocr_text` | Recognized text for one image (future NIM/OCR job). |
| `image_object_tag` | `image_id`, `tag_index`, `object_label` | Detected objects for image search (future). |

Do not store greeting text on `unit_embedding`. Do not collapse invoice and
greeting into one `source_document` row and call it searched.

## Persistence Stack

- PostgreSQL for the primary store.
- SQLAlchemy 2.x ORM mappings for Python services.
- Alembic autogenerate may draft migrations, but humans review object names and downgrade behavior.

