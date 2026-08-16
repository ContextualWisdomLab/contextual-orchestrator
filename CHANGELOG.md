# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- Treat official-SDK JSON `null` on optional `tools[].function.description`,
  `parameters`, and `strict` as omit-real: the keys are popped before
  `proxy_completion` so upstream providers see an omitted field, not a null
  schema. Non-null wrong types still fail closed with named `invalid_tools`.
  Next action: send those fields only when you have a real string, JSON Schema
  object, or boolean; SDK defaults of `null` are safe.

### References

- OpenAI. (2024). *Create chat completion*. OpenAI API reference.
  https://platform.openai.com/docs/api-reference/chat/create
- Bray, T. (Ed.). (2017). *The JavaScript Object Notation (JSON) data
  interchange format* (RFC 8259). Internet Engineering Task Force.
  https://doi.org/10.17487/RFC8259
