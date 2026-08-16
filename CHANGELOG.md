# Changelog

All notable changes to this project are documented here.

## Unreleased

### Added

- Meaning-unit embeddings chunking for `/v1/batch/embeddings`: header, paragraph, sentence, and `data:image` units keep source offsets so naruon can search SKU lines and senders without mixing them into a due-date vector. The naruon one-vector-per-input reduce is unchanged; read `meaning_units` for unit-level search.
