# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- Trusted orchestration traces no longer irreversibly mask email addresses.
  Credential shapes (`api_key=`, `Bearer …`) stay `[REDACTED]`. Access control
  (opt-in `include_orchestration_trace`) plus audit is the PII control, not
  destruction of the identifier an operator needs to close an invoice or HR
  ticket. Next action: request the trace only from a trusted caller; do not
  expect emails in that trace to become `[REDACTED]`.

### Fixed

- Gateway Bearer authenticators (`gateway_auth_token`, `admin_auth_token`,
  `inference_auth_token`) resolve from the credential KV. `--auth-token`
  and the split pair still win. `CONTEXTUAL_ORCHESTRATOR_TOKEN` /
  `_ADMIN_TOKEN` / `_INFERENCE_TOKEN` are copied into those KV names once
  at process start (`seed_server_auth_from_environ`). Seed and resolve
  strip surrounding whitespace so a mounted-secret newline still
  authorizes. Changing the env var on a running process — or restarting
  after the KV name is already set — no longer changes who can call the
  API. Buyer next action: pass `--auth-token` (or start once with the
  env var so bootstrap can copy it), then send that Bearer value. Rotate
  a persisted key with `--auth-token` or `register-credential`.
- Provider host allowlisting (`provider_egress.allowed_provider_hosts`) is
  read from the **process-wide runtime ConfigStore** at request time, not from
  `os.getenv` and not from a separately constructed Postgres `com_config`
  unless that store was installed with `set_runtime_config_store()` at
  bootstrap. `CONTEXTUAL_ORCHESTRATOR_ALLOWED_PROVIDER_HOSTS` is copied into
  that KV key once at process start (`seed_provider_egress_from_environ`).
  Changing the env var on a running process no longer changes egress policy.
  Buyer next action: call `set_runtime_config("provider_egress",
  "allowed_provider_hosts", "api.example.com")` (or start the process with
  the env var set so bootstrap can copy it). Do not write the key only into
  a new `get_config_store(postgres_dsn=...)` instance and expect egress to
  honor it.
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

- McCallister, E., Grance, T., & Scarfone, K. (2010). *Guide to protecting
  the confidentiality of personally identifiable information (PII)* (NIST
  Special Publication 800-122). National Institute of Standards and
  Technology. https://doi.org/10.6028/NIST.SP.800-122
- Joint Task Force. (2020). *Security and privacy controls for information
  systems and organizations* (NIST Special Publication 800-53 Rev. 5).
  National Institute of Standards and Technology.
  https://doi.org/10.6028/NIST.SP.800-53r5
- Grassi, P. A., Garcia, M. E., & Fenton, J. L. (2017). *Digital identity
  guidelines: Authentication and lifecycle management* (NIST Special
  Publication 800-63B). National Institute of Standards and Technology.
  https://doi.org/10.6028/NIST.SP.800-63b
- International Organization for Standardization. (2022). *Information
  security, cybersecurity and privacy protection — Information security
  controls* (ISO/IEC 27001:2022). https://www.iso.org/standard/27001
- OpenAI. (2024). *Create chat completion*. OpenAI API reference.
  https://platform.openai.com/docs/api-reference/chat/create
- Bray, T. (Ed.). (2017). *The JavaScript Object Notation (JSON) data
  interchange format* (RFC 8259). Internet Engineering Task Force.
  https://doi.org/10.17487/RFC8259
