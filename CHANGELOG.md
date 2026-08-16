# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- Trusted traces no longer replace requester email addresses with
  `[REDACTED]`. Secret shapes (API keys, bearer tokens, password/token
  assignments) are still destroyed. Confidentiality for operational PII is
  bearer-scope access plus audit, not irreversible masking. Next action: use
  an authorized token to read a failed-run trace and email the requester
  shown in the step output.

### Fixed

- Provider host allowlisting (`provider_egress.allowed_provider_hosts`) is
  read from the process KV at request time. `CONTEXTUAL_ORCHESTRATOR_ALLOWED_PROVIDER_HOSTS`
  is copied into that KV key once at process start (`seed_provider_egress_from_environ`).
  Changing the env var on a running process no longer changes egress policy.
  Next action: seed the allowlist into the KV, or start the process with the
  env var set so bootstrap can copy it.
- Treat official-SDK JSON `null` on optional `tools[].function.description`,
  `parameters`, and `strict` as omit-real: the keys are popped before
  `proxy_completion` so upstream providers see an omitted field, not a null
  schema. Non-null wrong types still fail closed with named `invalid_tools`.
  Next action: send those fields only when you have a real string, JSON Schema
  object, or boolean; SDK defaults of `null` are safe.
- Fail closed on tools passthrough for `seed`, `stop`, `n>1`, `logprobs`,
  `logit_bias`, and out-of-range penalties — the same named errors as the
  orchestration path. Next action: omit those knobs on tool-calling requests.
- Apply the request `temperature` on streamed route completions instead of
  silently using `0.2`. Next action: send the temperature you want; streaming
  no longer changes the sampling policy.

### References

- OpenAI. (2024). *Create chat completion*. OpenAI API reference.
  https://platform.openai.com/docs/api-reference/chat/create
- Bray, T. (Ed.). (2017). *The JavaScript Object Notation (JSON) data
  interchange format* (RFC 8259). Internet Engineering Task Force.
  https://doi.org/10.17487/RFC8259
- Joint Task Force. (2020). *Security and privacy controls for information
  systems and organizations* (NIST Special Publication 800-53 Rev. 5).
  National Institute of Standards and Technology.
  https://doi.org/10.6028/NIST.SP.800-53r5
- International Organization for Standardization. (2022). *Information
  security, cybersecurity and privacy protection — Information security
  controls* (ISO/IEC 27001:2022). https://www.iso.org/standard/27001
- International Organization for Standardization. (2024). *Information
  technology — Security techniques — Privacy framework* (ISO/IEC 29100:2024).
  https://www.iso.org/standard/85938.html
- McCallister, E., Grance, T., & Scarfone, K. (2010). *Guide to protecting
  the confidentiality of personally identifiable information (PII)*
  (NIST Special Publication 800-122). National Institute of Standards and
  Technology. https://doi.org/10.6028/NIST.SP.800-122
