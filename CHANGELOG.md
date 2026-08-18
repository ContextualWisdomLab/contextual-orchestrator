# Changelog

All notable changes introduced after the initial repository bootstrap are recorded here.

## [Unreleased]

### Fixed

- Added cross-agent provider fallback for OpenAI-compatible passthrough requests, including tool-calling and Responses API traffic, so a rate-limited primary model can hand the unchanged request to the next eligible model while preserving the full provider response shape.
