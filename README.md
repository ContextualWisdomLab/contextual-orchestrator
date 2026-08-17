# Contextual Orchestrator

[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/ContextualWisdomLab/contextual-orchestrator)
[![Security](https://github.com/ContextualWisdomLab/contextual-orchestrator/actions/workflows/security.yml/badge.svg)](https://github.com/ContextualWisdomLab/contextual-orchestrator/actions/workflows/security.yml)

One OpenAI-compatible API that **routes, delegates, verifies, and synthesizes** work across a configurable pool of model agents.

Callers keep using `/v1/chat/completions`. Behind that front door the orchestrator picks a fast single-worker path or a deeper workflow, exposes only the prior outputs each step is allowed to see, and returns a normal chat completion (or an SSE stream).

This is not a Sakana AI product and does not reproduce their trained models. It implements the public control-plane pattern: one model-like interface, with the agent pool, routing, workflow, and verification kept behind it.

## Why operators use it

Contextual Orchestrator is the org's **cost-review and sync-vs-batch routing hub** — a LiteLLM-plus scope: cost accounting, upstream selection, and batch routing from one place.

- **Cost review.** Every completion (sync and batch) records prompt-safe usage: tokens, cost when a price is configured, provider, model, and seven attribution dimensions (account, service, upstream API/provider, model name, team, group, company). Estimates are labeled; unpriced models stay `null`. Raw prompt and answer text are not stored on the usage record.
- **Sync vs batch.** `RoutingPolicy` keeps interactive chat on the fast path and sends latency-tolerant or bulk work to a batch backend ([pg-llm-batch](https://github.com/ContextualWisdomLab/pg-llm-batch) in production; an in-process backend when you run standalone).
- **One adoption surface.** Existing OpenAI-compatible clients do not need a new SDK. Operators get `/admin` for pool, policy, trace, and spend review.

Provider secrets are resolved from a KV credential registry, not from `os.getenv` at request time. See [docs/kv-credentials.md](docs/kv-credentials.md).

## Quick start

CLI (mock agents, offline):

```bash
python -m contextual_orchestrator "Summarize why model orchestration helps long coding tasks." \
  --agents examples/agents.mock.json
```

Serve the OpenAI-compatible API and operator console:

```bash
export CONTEXTUAL_ORCHESTRATOR_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
python -m contextual_orchestrator --serve --agents examples/agents.mock.json --port 8000
```

Admin console: [http://127.0.0.1:8000/admin](http://127.0.0.1:8000/admin)

```bash
curl -s http://127.0.0.1:8000/v1/chat/completions \
  -H "authorization: Bearer $CONTEXTUAL_ORCHESTRATOR_TOKEN" \
  -H 'content-type: application/json' \
  -d '{"model":"contextual-orchestrator","messages":[{"role":"user","content":"Analyze this code review task and verify the answer."}]}'
```

Seed a provider key into the KV once, then point agents at real `https://` endpoints:

```bash
echo "$OPENAI_API_KEY" | python -m contextual_orchestrator register-credential --name OPENAI_API_KEY --value-stdin
```

## Documentation

| Doc | What it covers |
| --- | --- |
| [Architecture](docs/architecture.md) | Route vs conduct, Trinity roles, Conductor access lists, Fugu latency/quality split |
| [Papers](docs/papers/README.md) | APA 7th citations and what each paper grounds in this repo |
| [REST API design](docs/rest_api_design.md) | Compatibility chat endpoint, operator resources, OpenAPI contract |
| [KV credentials](docs/kv-credentials.md) | `get_credential` seam, backends, bootstrap vs runtime |
| [Architecture decision records](docs/adr/) | Why the public API, cost routing, roles, and latency split look this way |

Buyer diligence packets, saleability gates, and the verification checklist live in [docs/doctoring/](docs/doctoring/README.md) and the existing `docs/commercial_*.md` files. Those indexes include the buyer acceptance workflow (`/api/v1/commercial_buyer_acceptance_workflows/latest`), commercial demo scenarios (`/api/v1/commercial_demo_scenarios/latest`), commercial proposal packet (`/api/v1/commercial_proposal_packets/latest`), commercial purchase approval packet (`/api/v1/commercial_purchase_approval_packets/latest`), commercial due diligence room (`/api/v1/commercial_due_diligence_rooms/latest`), and commercial investment committee memo (`/api/v1/commercial_investment_committee_memos/latest`).
