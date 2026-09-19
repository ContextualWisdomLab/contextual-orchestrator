# i18n Design

## Locales

- `en`: default and fallback locale.
- `ko`: Korean operator locale.

## Resource Model

UI messages are locale bundles:

- REST: `GET /api/v1/locale_bundles/{locale_code}`
- Admin runtime: inlined bundle for the dependency-free prototype.
- Production runtime: i18next resources loaded over HTTP.

## Key Rules

- Translation keys use lower snake_case with at least two words.
- No concatenated sentence fragments.
- Operational IDs, role names, and model names are not translated.
- Locale selection persists in `localStorage`.
- Fallback locale is English.

## Current Implementation

`contextual_orchestrator.admin.ADMIN_TRANSLATIONS` contains English and Korean bundles. The admin console switches language without a page reload.

## Production Library Target

Use i18next for resource loading, fallback language, interpolation, language detection, and runtime switching. React-admin should receive an `i18nProvider` backed by the same bundles.

