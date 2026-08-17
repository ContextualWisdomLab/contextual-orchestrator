# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `chunking_strategy=meaning_units` on `POST /v1/batch/embeddings` embeds email
  parties, HTML blocks, embedded images, and paragraphs as separate vectors and
  returns `chunk_units` with source offsets. Omit the field to keep the naruon
  one-vector-per-input contract. Next action: send the raw invoice email and
  search `chunk_units` for the invoice id.

### Fixed

- Meaning-unit HTML cuts keep innermost leaves, so a wrapped
  `<div><p>Good morning</p><p>Invoice INV-…</p></div>` no longer becomes one
  vector. RFC 2397 `data:image` units now accept charset parameters, URL-safe
  `-_`, and RFC 2045 folds (76-column wraps and short padded last lines) so
  leftover base64 does not glue onto the balance paragraph. Next action:
  POST the raw Gmail HTML or a column-76 MIME wrap with
  `chunking_strategy=meaning_units` and search `chunk_units`.
- HTML meaning-unit cuts walk to the first matching close tag instead of a
  backtracking `.*?` matcher, so nested unclosed wrappers cannot stall a
  batch. Tag-only leftovers use the same linear walk instead of a repeating
  `(?:\s*</?[A-Za-z][^>]*>\s*)+` matcher, so `<A> <A>…` prefixes cannot
  stall a batch. Ledger SQL uses complete bind-parameter statements (no
  execute-time concatenation). Provider TLS opt-out and validated `urlopen`
  keep audited Semgrep annotations.
- OpenAPI `chunking_strategy` accepts JSON null alongside `meaning_units`.
  Async 202 and GET completed embeddings responses document optional
  `chunk_units`. A body line that begins `Subject:` is not a second email
  header.
