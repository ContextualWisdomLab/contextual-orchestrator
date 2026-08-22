# ADR 0123: Omit Unsupported Sampling Defaults

- Status: Accepted
- Date: 2026-08-21

## Context

Reasoning-capable providers can reject a `temperature` field even when the
value is a conventional default such as `0.2`. A gateway that invents this
field before capability negotiation makes an otherwise valid discovered model
unusable and can turn failover into a false provider outage. Azure's current
reasoning-model documentation explicitly lists `temperature` among the
unsupported parameters (Microsoft, 2026).

## Decision

The orchestrator omits `temperature` and other optional sampling controls when
the caller did not explicitly provide them. The provider and selected model
therefore own their documented defaults and capability handling. Explicit
values remain validated at the public request boundary and are forwarded
unchanged through chat, streaming, batch, and structured-output transport
paths. A client-level explicit value, including the CLI option, applies to
ordinary chat as well as streaming and batch calls; a request-scoped value
temporarily overrides it for both streamed and non-streamed requests. HTTP
request overrides are isolated from concurrent requests; the server must not
mutate shared client defaults while a request is in flight.

The command-line sampling option is optional and defaults to omission. Health
probes also omit sampling controls; a probe must test reachability without
assuming that the model accepts a sampling parameter.

This is a transport-capability contract, not a model-ranking heuristic. Model
selection and reasoning-effort policy remain governed by the paper-grounded
model policy ADRs.

## Consequences

- Reasoning models that reject `temperature` can be selected without a local
  model-name exception.
- Callers that require a sampling value must state it explicitly and accept the
  selected provider's capability response.
- One request's explicit controls cannot become another request's implicit
  defaults.
- Provider request assertions must distinguish omitted fields from explicit
  values.

## References

Microsoft. (2026, August 6). *Azure OpenAI reasoning models: GPT-5 series,
o3-mini, o1, o1-mini*. Microsoft Learn.
https://learn.microsoft.com/azure/foundry/openai/how-to/reasoning
