# Changelog

All notable changes to this project are documented in this file.

## [Unreleased]

### Added

- A transport-neutral, versioned model fallback policy that validates explicit
  cost tiers and deterministically exhausts eligible free candidates before
  any paid fallback.
- Runtime filtering by repository visibility, required capability, and
  configured credential name without retaining or serializing secret values.
- A standard-library CLI for immutable cross-repository workflow integration.
- 100% statement and branch coverage for the fallback policy and strict JSON
  manifest parser.
