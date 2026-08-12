# i18n Design

**Document state:** `implemented_on_protected_main` for the inline locale
bundles and `planned` for the adoption candidate described below.

## Locales

- `en`: default and fallback locale.
- `ko`: Korean operator locale.

## Resource Model

UI messages are locale bundles:

- REST: `GET /api/v1/locale_bundles/{locale_code}`
- Admin runtime: inlined bundle in the standalone runtime.
- Planned web client: i18next resources loaded over HTTP.

## Key Rules

- Translation keys use lower snake_case with at least two words.
- No concatenated sentence fragments.
- Operational IDs, role names, and model names are not translated.
- Locale selection persists in `localStorage`.
- Fallback locale is English.

## Current Implementation

`contextual_orchestrator.admin.ADMIN_TRANSLATIONS` contains English and Korean bundles. The admin console switches language without a page reload.

## Planned adoption candidate

i18next and React-admin are planned adoption candidates. Adopt them for a
separately built web client only with migration, rollback, and parity evidence;
they do not own the current inline admin call path.
