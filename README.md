# Contextual Orchestrator

**One model-like API for governed multi-model orchestration.**

[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/ContextualWisdomLab/contextual-orchestrator)
[![Security](https://github.com/ContextualWisdomLab/contextual-orchestrator/actions/workflows/security.yml/badge.svg)](https://github.com/ContextualWisdomLab/contextual-orchestrator/actions/workflows/security.yml)

Contextual Orchestrator is an enterprise-oriented orchestration control plane for OpenAI-compatible model workers. Applications keep a familiar inference API while operators gain a managed model pool, routing policy, workflow traceability, verification evidence, provider controls, and an admin surface for understanding what happened inside each run.

It is designed for teams that want collective model intelligence without forcing every application to build and govern its own multi-agent stack.

> Contextual Orchestrator is not a Sakana AI product and does not reproduce Sakana-trained models. It implements a public orchestration pattern around a configurable worker pool while preserving its own product, security, and governance boundaries.

## Why it exists

A single model endpoint is easy to adopt. A production orchestration layer is harder: teams must decide which model should handle a task, when deeper workflows are worth the latency, which providers may receive context, how verification was performed, and what evidence operators can inspect afterward.

Contextual Orchestrator makes those decisions explicit behind one model-like interface.

| Need | What Contextual Orchestrator provides |
| --- | --- |
| Compatible adoption | OpenAI-compatible chat and Responses-facing interfaces |
| Model choice | Configurable worker agents, model groups, discovery, health, cost and exclusion metadata |
| Fast vs. deep work | Deterministic route/conduct orchestration policies and mode overrides |
| Explainability | Workflow traces with roles, subtasks, workers and verifier outcomes |
| Provider governance | KV-backed credentials, provider allowlisting and fail-closed routing boundaries |
| Operations | Admin console, readiness, audit, analytics and spend evidence |
| Evaluation | Replay and baseline comparison without presenting structural metrics as human-quality claims |
| Global operations | First-class English and Korean operator copy |

## Choose your path

### Run the full local stack

The canonical deployment path for local evaluation is `compose.yaml`. It starts PostgreSQL, uses separate admin and inference tokens from Compose secrets, and binds the gateway to loopback.

```bash
umask 077
mkdir -p .secrets
chmod 700 .secrets
printf '%s' 'replace-with-a-long-random-admin-token' > .secrets/admin-token
printf '%s' 'replace-with-a-long-random-inference-token' > .secrets/inference-token
chmod 600 .secrets/admin-token .secrets/inference-token

export INFERENCE_TOKEN="$(cat .secrets/inference-token)"
export CONTEXTUAL_ORCHESTRATOR_POSTGRES_PASSWORD='replace-with-a-database-password'
export CONTEXTUAL_ORCHESTRATOR_KV_PASSPHRASE='replace-with-an-encryption-passphrase'

docker compose up --build --wait
curl http://127.0.0.1:8000/healthz
```

Provider credentials are registered separately through the credential registry; they do not belong in `compose.yaml` or the gateway process environment.

```bash
echo "$OPENAI_API_KEY" | \
  python -m contextual_orchestrator register-credential \
  --name OPENAI_API_KEY \
  --value-stdin
```

Then call the OpenAI-compatible Responses surface. `orchestrator/auto` selects from configured model groups; `orchestrator/free` is the fail-closed zero-cost pool when qualifying free candidates are available.

```bash
curl -N http://127.0.0.1:8000/v1/responses \
  -H "Authorization: Bearer $INFERENCE_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "orchestrator/free",
    "input": "Research and verify this",
    "reasoning": {"summary": "auto"},
    "stream": true
  }'
```

### Try the orchestration engine with mock workers

For a lightweight local run that does not require provider credentials:

```bash
python -m contextual_orchestrator \
  "Summarize why model orchestration helps long coding tasks." \
  --agents examples/agents.mock.json
```

Serve the local API with a generated development token:

```bash
local_token="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"

python -m contextual_orchestrator \
  --serve \
  --agents examples/agents.mock.json \
  --port 8000 \
  --auth-token "$local_token"
```

```bash
curl -s http://127.0.0.1:8000/v1/chat/completions \
  -H "Authorization: Bearer $local_token" \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "contextual-orchestrator",
    "messages": [
      {"role": "user", "content": "Analyze this code review task and verify the answer."}
    ]
  }' | jq .
```

The admin console is available at `http://127.0.0.1:8000/admin`.

## Core concepts

### One public control-plane model

`contextual-orchestrator` is the model-like control-plane candidate exposed to callers. The worker pool, routing logic, multi-step workflow, verification and synthesis stay behind that interface.

### Managed worker pool

Workers can be seeded from configuration and managed through the admin/API surface. Runtime changes can remain in-memory or be persisted with `--agents-db PATH`. Remote discovery can populate candidates from configured providers, while discovered candidates remain governed rather than silently becoming active routing truth.

```bash
python -m contextual_orchestrator discover-models --agents-db ./agents.sqlite3
```

The full local candidate example is in [`examples/agents.local.json`](examples/agents.local.json).

### Model groups

Model groups let operators treat provider/model candidates as a governed pool rather than hard-coding one endpoint everywhere. Routing can consider health, availability, cost evidence, priority and exclusions without claiming that transient discovery metadata is permanent product truth.

### Route vs. conduct

Simple requests can be routed to one worker. Harder requests can use a short orchestration workflow that delegates subtasks and verifies the synthesized result. The product intentionally exposes the latency-quality tradeoff rather than hiding it as magic.

### Traceability by design

Trusted callers and operators can inspect orchestration evidence such as mode, contributing steps, worker assignments and verification outcomes. Full traces are not disclosed by default; trace exposure is opt-in and restricted where structured/tool framing would make disclosure ambiguous.

## Provider and credential boundary

Real workers use OpenAI-compatible endpoints and resolve secrets from the KV credential registry via `get_credential`. A missing credential fails closed instead of falling back to request-time environment lookup.

```json
{
  "agents": [
    {
      "id": "coding_agent",
      "model": "gpt-5.5",
      "base_url": "https://api.openai.com/v1",
      "credential_key": "OPENAI_API_KEY",
      "tags": ["coding", "debugging", "reasoning"]
    }
  ]
}
```

For a local `mlx-lm` OpenAI-compatible server, use the explicit loopback-only `mlx://` scheme:

```json
{
  "agents": [
    {
      "id": "local_fast_agent",
      "model": "mlx-community/llama-3.2-3b-instruct-4bit",
      "base_url": "mlx://127.0.0.1:8080/v1",
      "provider_name": "mlx-lm",
      "tags": ["reasoning", "coding", "verification"]
    }
  ]
}
```

Non-mock remote providers must use `https://`. The runtime blocks loopback, private, link-local, multicast and reserved provider destinations before sending credentials unless an explicit reviewed gateway boundary is configured.

See [`docs/kv-credentials.md`](docs/kv-credentials.md) for credential registration, provider discovery and deployment details.

## Architecture at a glance

```text
Application / SDK
       │
       │ OpenAI-compatible request
       ▼
┌──────────────────────────────┐
│   Contextual Orchestrator    │
│  public control-plane model  │
├──────────────────────────────┤
│ request validation           │
│ routing / orchestration      │
│ policy and access controls   │
│ verification and synthesis   │
│ trace / audit / analytics    │
└──────────────┬───────────────┘
               │
       governed worker pool
               │
     ┌─────────┼─────────┐
     ▼         ▼         ▼
 OpenAI-   OpenRouter   local /
 compatible   ...       approved gateways
 workers
```

The repository owns orchestration, routing, provider/model pool management, trace evidence and the compatible gateway boundary. It does not claim ownership of every adjacent ecosystem concern. Dedicated identity, sandbox, psychometric, document and enterprise-architecture products remain separate authorities and integrate through explicit contracts.

## Operational surfaces

The API and admin plane include bounded operational evidence for areas such as:

- authenticated readiness and provider readiness;
- agent-pool and model-group management;
- workflow and audit traces;
- source-backed local analytics;
- measured token/cost evidence when providers or supported tokenizers make that evidence available;
- evaluation replay and baseline comparison;
- enterprise-pilot and commercial due-diligence readiness evidence.

Readiness and commercial endpoints are evidence/reporting surfaces. They are not compliance certifications, valuation guarantees, customer commitments or substitutes for deployment-specific review.

## Security posture

The local lab defaults are intentionally conservative:

- `/healthz` is the minimal unauthenticated liveness probe; authenticated `/readyz` carries operational readiness evidence.
- Administrative and inference surfaces require authorization.
- Public binding requires explicit opt-in and production mode rejects insecure single-token/cookie shortcuts.
- Provider credentials are resolved through the credential registry and are never intentionally returned in traces.
- Provider destinations are validated before secrets can leave the process.
- Request bodies, roles, modes, sizes, rates and concurrent runs are bounded before orchestration begins.
- Optional persistence does not silently change the in-memory default.

A production deployment using the ecosystem identity plane must inject a reviewed bearer verifier for Keyverse-issued OIDC tokens. The core does not hand-roll JWT verification or hold identity-provider admin credentials.

For the current workflow security checks, see the [Security workflow](https://github.com/ContextualWisdomLab/contextual-orchestrator/actions/workflows/security.yml).

## Installation and runtime

The Python package is `contextual-orchestrator` version `0.2.0` in the current source tree and requires Python 3.10 or newer. Optional dependency groups cover API serving, database integration, queues, fuzzing and tests.

For source development, install the checkout using your preferred Python environment tooling, then run the module entry point:

```bash
python -m contextual_orchestrator --help
```

`fast-mlsirm` is used for model-based conduct verification on supported Python versions. Live judge workflows fail closed when that dependency or its contextual contract is unavailable. Verify the exact interpreter used for the run with:

```bash
python -m contextual_orchestrator check-fast-mlsirm
```

## Documentation map

Start here rather than treating the README as the full operator manual:

- [`docs/product_planning.md`](docs/product_planning.md) — product thesis, personas, bets and deliberate non-goals.
- [`docs/model-group-product-technical-spec.md`](docs/model-group-product-technical-spec.md) — model-group product and technical specification.
- [`docs/product-technical-gap-baseline.md`](docs/product-technical-gap-baseline.md) — current product/technical gap evidence and claim boundaries.
- [`docs/kv-credentials.md`](docs/kv-credentials.md) — credential registry, discovery and provider setup.
- [`docs/planning/adrs/`](docs/planning/adrs/) — architecture decision records.
- [`examples/`](examples/) — mock and local worker-pool examples.

## Product principles

Contextual Orchestrator is developed around a few explicit constraints:

1. **Compatibility is the adoption wedge.** Applications should not need to learn a bespoke orchestration protocol first.
2. **Traceability is a product capability.** Operators need to know what work happened, where, and why.
3. **Provider governance is runtime evidence.** Exclusions, access boundaries and health belong next to the run they influenced.
4. **Latency vs. depth is a policy decision.** Deeper orchestration should be visible and tunable.
5. **Claims stay evidence-bound.** Local analytics, benchmark structure and readiness gates are not promoted into unsupported quality, compliance or commercial claims.
6. **Repository boundaries matter.** Adjacent ContextualWisdomLab products remain authoritative for their own domains.

## Contributing

Before changing orchestration behavior, read the product planning, applicable PRD/specification and architecture decisions. Preserve fail-closed security boundaries, keep claims tied to current code and evidence, and update tests/docs together when a public contract changes.

See [`CONTRIBUTING.md`](CONTRIBUTING.md) if present in the checkout and the repository's `AGENTS.md` / architecture guidance for contributor-specific rules.

## License

Contextual Orchestrator is licensed under the [MIT License](LICENSE).
