# Ecosystem connectors

`contextual-orchestrator` is the org LLM gateway. Other ContextualWisdomLab
programs consume it as an OpenAI-compatible base URL (standalone process or git
submodule). This note records high-leverage integration order.

## Consumers (call into this gateway)

| Product | Integration | Status |
|---|---|---|
| **scopeweave** | Point agent HTTP clients at `/v1/chat/completions` with a Bearer inference token. | Compatible; no hard dependency required. |
| **free-router** | Discovers free NIM/OpenRouter models; operators can register winners as agents here with `model_group` replicas for race failover. | Documented pairing; free-router remains a discovery CLI. |
| **naruon** | Email/PIM hub — long-running orchestration can use conduct mode + cost ledger attribution. | Planned via gateway base URL. |
| **gyeot** (if present) | Same OpenAI-compatible surface as scopeweave. | Org consumer. |

## Sidecars (this gateway calls out)

| Product | Integration | Status |
|---|---|---|
| **pg-llm-batch** | Batch/embeddings backends via `batch_routing` (in-process backend keeps standalone path). | Wired. |
| **clearfolio** | Admin document viewer via `--clearfolio-url`. | Wired. |
| **keyverse** | Identity is out of scope for this repo (ADR); credentials write into local KV only. | Boundary documented. |
| **EgressWeave** | Future hardening option for provider egress pinning beyond stdlib SSRF checks. | Optional future. |

## Agent pool pattern (MSA)

Each consumer keeps its own agent pool JSON. Example replica race:

```json
[
  {
    "id": "nim_replica_a",
    "model": "meta/llama-3.1-70b-instruct",
    "base_url": "https://integrate.api.nvidia.com/v1",
    "credential_key": "NVIDIA_NIM_API_KEY",
    "model_group": "nim_llama70b_pool",
    "tags": ["reasoning", "writing"],
    "priority": 5
  },
  {
    "id": "nim_replica_b",
    "model": "meta/llama-3.1-70b-instruct",
    "base_url": "https://integrate.api.nvidia.com/v1",
    "credential_key": "NVIDIA_NIM_API_KEY",
    "model_group": "nim_llama70b_pool",
    "tags": ["reasoning", "writing"],
    "priority": 4
  }
]
```

Replicas sharing `model_group` race for first valid completion (issue #102).
Distinct paper roles (thinker/worker/verifier/synthesizer) stay independently
selected.

## Bootstrap

```bash
echo "$NVIDIA_NIM_API_KEY" | python -m contextual_orchestrator \
  register-credential --name NVIDIA_NIM_API_KEY --value-stdin
python -m contextual_orchestrator --serve \
  --agents examples/agents.openai.json \
  --admin-token "$ADMIN" --inference-token "$INFER"
```

Live model tests must use `NVIDIA_NIM_API_KEY` only — never
`COPILOT_GITHUB_TOKEN`. OpenCode/Noema/Strix **review** agents remain on their
existing GitHub Models key setup.
