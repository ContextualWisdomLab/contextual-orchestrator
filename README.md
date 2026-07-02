# Contextual Orchestrator

[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/ContextualWisdomLab/contextual-orchestrator)
[![Security](https://github.com/ContextualWisdomLab/contextual-orchestrator/actions/workflows/security.yml/badge.svg)](https://github.com/ContextualWisdomLab/contextual-orchestrator/actions/workflows/security.yml)

Stdlib Python lab for a single API that routes, delegates, verifies, and synthesizes work across a configurable pool of OpenAI-compatible model agents.

This is not a Sakana AI product or a reproduction of their trained models. It is a small implementation of the public architecture pattern: expose one model-like interface while keeping the agent pool, routing, workflow, and verification logic behind it.

## Quick Start

```bash
python -m contextual_orchestrator "Summarize why model orchestration helps long coding tasks." \
  --agents examples/agents.mock.json
```

Run the OpenAI-compatible subset:

```bash
export CONTEXTUAL_ORCHESTRATOR_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
python -m contextual_orchestrator --serve --agents examples/agents.mock.json --port 8000
```

Admin console:

```text
http://127.0.0.1:8000/admin
```

```bash
curl -s http://127.0.0.1:8000/v1/chat/completions \
  -H "authorization: Bearer $CONTEXTUAL_ORCHESTRATOR_TOKEN" \
  -H 'content-type: application/json' \
  -d '{"model":"contextual-orchestrator","messages":[{"role":"user","content":"Analyze this code review task and verify the answer."}]}' | jq .
```

HTTP serving is hardened for local lab use:

- `/admin`, `/admin/state`, `/api/v1/*`, and `/v1/chat/completions` require a Bearer token. Use `--admin-token` and `--inference-token` to separate operator and runtime access, or `--auth-token` / `CONTEXTUAL_ORCHESTRATOR_TOKEN` for one local-development token.
- Binding to `0.0.0.0` or `::` requires `--allow-public-bind`.
- JSON request bodies, chat message roles, orchestration modes, body sizes, request rate, and concurrent run counts are validated before orchestration runs.
- Full orchestration traces are not returned by default. Set `include_orchestration_trace: true` per chat request or start with `--expose-trace-by-default` when the caller is trusted.

Use real workers by replacing `mock://` agents with OpenAI-compatible endpoints and environment-backed API keys:

```json
{
  "agents": [
    {
      "id": "coding_agent",
      "model": "gpt-5.5",
      "base_url": "https://api.openai.com/v1",
      "api_key_env": "OPENAI_API_KEY",
      "tags": ["coding", "debugging", "reasoning"]
    }
  ]
}
```

Non-mock providers must use `https://` URLs and an explicit `api_key_env`. The runtime blocks loopback, private, link-local, multicast, and reserved provider addresses before sending a key. Set `CONTEXTUAL_ORCHESTRATOR_ALLOWED_PROVIDER_HOSTS` to a comma-separated host allowlist when only approved model gateways should be reachable. External calls use a timeout and default output token cap.

## Architecture

One public interface:

- `/v1/chat/completions` accepts normal chat messages.
- `TaskOrchestrator.complete()` decides whether to route to one worker or run a short workflow.
- Responses include orchestration mode metadata, and trusted callers can request the full trace for audit.
- `/admin` exposes an operator console for agent pool, policy, trace, and audit review.
- `/api/v1/sales_readiness/latest` exposes a local enterprise-pilot readiness gate for API compatibility, operator evidence, workflow traces, evaluation replay, security posture, analytics truthfulness, locale parity, and provider egress safety. It is process-local evidence, not a production compliance certificate.
- `/api/v1/commercial_readiness/latest` exposes a KRW 2,000,000,000 commercial due-diligence readiness gate. It is a buyer-review evidence snapshot, not a valuation guarantee or purchase commitment.

One fused orchestration loop:

- Fast path: one worker is selected for simple or latency-sensitive requests.
- Deep path: a natural-language workflow is built with planner, worker, verifier, and synthesizer steps.
- Each step has an access list, so workers see only the prior outputs intentionally exposed to them.
- Agent definitions are data, so provider preference, exclusions, privacy constraints, and mock testing do not require code changes.

See [docs/architecture.md](docs/architecture.md) for the source-backed analysis.

## Design Artifacts

- [Library research](docs/library_research.md)
- [Product planning](docs/product_planning.md)
- [Screen design](docs/screen_design.md)
- [User stories](docs/user_stories.md)
- [REST API design](docs/rest_api_design.md)
- [Code conventions](docs/code_conventions.md)
- [Database conventions](docs/database_conventions.md)
- [i18n design](docs/i18n_design.md)
- [Plugin-driven design brief](docs/plugin_driven_design_brief.md)
- [Plugin visual directions](docs/plugin_visual_directions.md)
- [Analytics spec](docs/analytics_spec.md)
- [Commercial readiness standard](docs/commercial_readiness.md)
- [Commercial completion scorecard](docs/commercial_completion_scorecard.md)
- [Commercial plugin operating model](docs/commercial_plugin_operating_model.md)
- [Figma artifacts](docs/figma_artifacts.md)
- [Plugin-driven implementation plan](docs/superpowers/plans/2026-07-02-plugin-driven-product-design.md)
- [Commercial plugin readiness plan](docs/superpowers/plans/2026-07-02-commercial-plugin-readiness.md)

## Check

```bash
python -m pip install --require-hashes -r requirements.lock
python -m pip install --no-deps -e .
python tests/test_self_check.py
python tests/test_paper_contracts.py
python tests/test_admin_contract.py
python tests/test_conventions.py
python tests/test_api_contract.py
python tests/test_security_hardening.py
python tests/test_repository_security_metadata.py
python tests/test_product_planning_contract.py
python tests/test_plugin_driven_artifacts.py
python tests/test_analytics_runtime.py
python tests/test_sales_readiness.py
```
