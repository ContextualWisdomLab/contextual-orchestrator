# Changelog

All notable changes introduced after the initial repository bootstrap are recorded here.

## [Unreleased]

### Fixed

- Added cross-agent provider fallback for OpenAI-compatible passthrough requests, including tool-calling and Responses API traffic. Upstream request fields are preserved while each candidate receives its own model and non-streaming is enforced so a rate-limited primary can hand the request to the next eligible model without changing the provider response shape.
