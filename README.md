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
python -m contextual_orchestrator --serve --agents examples/agents.mock.json --port 8000
```

Admin console:

```text
http://127.0.0.1:8000/admin
```

```bash
curl -s http://127.0.0.1:8000/v1/chat/completions \
  -H 'content-type: application/json' \
  -d '{"model":"contextual-orchestrator","messages":[{"role":"user","content":"Analyze this code review task and verify the answer."}]}' | jq .
```

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

## Architecture

One public interface:

- `/v1/chat/completions` accepts normal chat messages.
- `TaskOrchestrator.complete()` decides whether to route to one worker or run a short workflow.
- Every response includes an orchestration trace so the caller can audit which agents were used.
- `/admin` exposes an operator console for agent pool, policy, trace, and audit review.

One fused orchestration loop:

- Fast path: one worker is selected for simple or latency-sensitive requests.
- Deep path: a natural-language workflow is built with planner, worker, verifier, and synthesizer steps.
- Each step has an access list, so workers see only the prior outputs intentionally exposed to them.
- Agent definitions are data, so provider preference, exclusions, privacy constraints, and mock testing do not require code changes.

See [docs/architecture.md](docs/architecture.md) for the source-backed analysis.

## Design Artifacts

- [Library research](docs/library_research.md)
- [Screen design](docs/screen_design.md)
- [User stories](docs/user_stories.md)
- [REST API design](docs/rest_api_design.md)
- [Code conventions](docs/code_conventions.md)
- [Database conventions](docs/database_conventions.md)
- [i18n design](docs/i18n_design.md)

## Check

```bash
python tests/test_self_check.py
python tests/test_paper_contracts.py
python tests/test_admin_contract.py
python tests/test_conventions.py
python tests/test_api_contract.py
python tests/test_repository_security_metadata.py
```
