# Changelog

All notable changes to this project are documented here. Dates are UTC.

## Unreleased

### Fixed

- Provider host allowlisting (`provider_egress.allowed_provider_hosts`) is
  read from the process KV at request time. `CONTEXTUAL_ORCHESTRATOR_ALLOWED_PROVIDER_HOSTS`
  is copied into that KV key once at process start (`seed_provider_egress_from_environ`).
  Changing the env var on a running process no longer changes egress policy.
  Buyer next action: seed the allowlist into the KV, or start the process with
  the env var set so bootstrap can copy it.

### Docs

- APA 7th citations for NIST SP 800-53 Rev. 5 SC-7 and ISO/IEC 27001:2022
  A.8.20 on the allowlist boundary-protection contract.
