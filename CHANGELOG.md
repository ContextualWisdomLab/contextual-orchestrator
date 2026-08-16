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
  `-_`, and MIME line wraps so a scanned invoice does not glue onto the
  balance paragraph. Next action: POST the raw Gmail HTML or MIME-wrapped
  scan with `chunking_strategy=meaning_units` and search `chunk_units`.
