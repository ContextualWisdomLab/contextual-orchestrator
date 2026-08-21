# ADR 0020: Keep raw provider failures inside the gateway

- Status: Accepted
- Date: 2026-08-21

## Context

Provider HTTP bodies and exception messages can contain credentials, prompt
content, personal data, internal URLs, or vendor diagnostics. Structured
orchestration, embeddings, retries, and cross-provider failover must not make
provider raw exceptions available through a public gateway error or an
exception cause.

## Decision

1. Chat, embedding, and passthrough transport failures expose only
   package-owned messages and never copy provider exception text.
2. Model discovery reports stable diagnostic codes without copying provider
   response or exception text.
3. Exhausted failover and structured-output parsing do not chain provider raw
   errors; deterministic local remediation remains available.
4. Provider diagnostics may be counted by allowlisted type/code in internal
   telemetry, but raw bodies, exception text, credentials, and prompts are not
   persisted or returned.

## Verification

`tests/test_model_discovery.py`, `tests/test_provider_reliability.py`, and
`tests/test_model_judge.py` assert that provider response text is absent from
public messages and causes. The full suite must remain green before merge.

## References

MITRE. (n.d.). *CWE-209: Generation of error message containing sensitive
information*. https://cwe.mitre.org/data/definitions/209.html

OWASP Foundation. (2023). *Application Security Verification Standard 4.0.3*.
https://owasp.org/www-project-application-security-verification-standard/
