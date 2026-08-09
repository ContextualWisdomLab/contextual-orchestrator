# Transport-neutral model fallback policy

`contextual_orchestrator.model_fallback` is a policy-only module for workflows
that already own their HTTP client, provider SDK, credential identity, and
review identity. It never opens a socket and never reads a credential value.
It validates a versioned JSON manifest, filters candidates by explicit runtime
constraints, and returns a deterministic execution order:

1. every eligible `free` candidate, ordered by numeric priority;
2. every eligible `paid` candidate, ordered by numeric priority;
3. declaration order as the final stable tie-breaker.

A paid candidate can therefore never jump ahead of an eligible free candidate.
Model names are not used to infer price. The operator must declare `cost_tier`
because provider pricing and trial availability change independently of code.

## Manifest

```json
{
  "schema_version": 1,
  "agents": {
    "noema": {
      "candidates": [
        {
          "candidate_id": "nvidia_nim_free_primary",
          "provider": "nvidia-nim",
          "model": "nvidia/nemotron-3-ultra-550b-a55b",
          "cost_tier": "free",
          "priority": 10,
          "required_credentials": ["NVIDIA_NIM_API_KEY"],
          "repository_visibilities": ["public"],
          "capabilities": ["text", "structured_output"]
        },
        {
          "candidate_id": "paid_fallback",
          "provider": "openai",
          "model": "gpt-5.6-luna",
          "cost_tier": "paid",
          "priority": 100,
          "required_credentials": ["OPENAI_API_KEY"],
          "repository_visibilities": ["public", "private", "internal"],
          "capabilities": ["text", "structured_output"]
        }
      ]
    }
  }
}
```

The parser rejects unknown keys, unsupported schema versions, duplicate
candidate IDs, duplicate provider/model targets, unsafe shell identifiers,
and empty candidate lists. Repository visibility, capability labels, and
credential **names** are policy data; secret values are never serialized.

## Python API

```python
from contextual_orchestrator import (
    FallbackContext,
    build_fallback_plan,
    load_fallback_manifest,
)

candidates = load_fallback_manifest(document, "noema")
plan = build_fallback_plan(
    candidates,
    context=FallbackContext(
        repository_visibility="public",
        available_credentials=frozenset({"NVIDIA_NIM_API_KEY", "OPENAI_API_KEY"}),
        required_capabilities=frozenset({"structured_output"}),
    ),
)
for candidate in plan.candidates:
    call_existing_transport(candidate)
```

The caller decides which provider errors, malformed outputs, timeouts, or
quality-gate failures advance to the next candidate. A workflow must accept an
answer only after its existing schema and security checks pass.

## CLI integration

The trusted composition root determines which credential identities are
available and passes only their validated names. The policy CLI never reads the
corresponding environment variables or any other secret-value store.

```bash
python -m contextual_orchestrator.model_fallback plan \
  --manifest config/llm-fallback-policy.json \
  --agent opencode-review \
  --repository-visibility public \
  --available-credential NVIDIA_NIM_API_KEY \
  --available-credential OPENAI_API_KEY \
  --required-capability structured_output \
  --format models
```

Use `--deny-paid` for an explicit free-only run. An empty eligible pool is a
hard error, not an implicit success. Credential names must satisfy the same
strict identifier grammar as manifest credential requirements.

## Integration boundary

Cross-repository consumers should materialize this repository at an immutable
commit SHA, verify the checkout, add only that checkout to `PYTHONPATH`, and
keep their existing provider and reviewer credentials scoped to the original
workflow job. This module is suitable for the central `.github` workflows,
`naruon`, and standalone services because it has no provider SDK dependency.
