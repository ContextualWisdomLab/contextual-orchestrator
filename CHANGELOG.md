# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- Treat Completions `max_tool_calls` as a named field: JSON null / empty /
  whitespace omit; any other value fails closed as `invalid_max_tool_calls`
  instead of opaque `unknown_fields`.
- Run chat message honesty (weight, prefix, refusal, annotations, role,
  content, name, tool_calls keys) **before** the tools/response_format
  passthrough so tool-using SDKs get the same named 400s as the no-tools path.
- Pop omit-equivalent `max_tool_calls` before provider proxy so null/empty
  values are not forwarded upstream.
- Bind Completions/chat sampling knobs (`temperature`, `top_p`, penalties,
  `max_tokens`) on `ModelClient` thread-local state. Concurrent requests on
  `ThreadingHTTPServer` no longer race shared `default_temperature`.

### References

- OpenAI. (n.d.). *Chat Completions API*. OpenAI Platform.
  https://platform.openai.com/docs/api-reference/chat/create
- Zhang, J., et al. (2025). *TRINITY: An evolved LLM coordinator*.
  arXiv. https://doi.org/10.48550/arXiv.2512.04695
- Zhang, J., et al. (2025). *Learning to orchestrate agents in natural language
  with the Conductor*. arXiv. https://doi.org/10.48550/arXiv.2512.04388
