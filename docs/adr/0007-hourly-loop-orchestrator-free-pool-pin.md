# ADR 0007: Pin the hourly OpenCode maintenance loop to `orchestrator/free`

- Status: Proposed
- Date: 2026-09-02
- Decision owners: ContextualWisdomLab
- Series: `docs/adr` only. This is not a planning-ADR number.

## Context

`.github/workflows/opencode-hourly-loop.yml` runs an hourly autonomous OpenCode
agent inside this repository's CI. Before this proposal, its OpenCode client
requested the virtual model id
`contextual_orchestrator_gateway/orchestrator/auto` in the OpenCode config and
CLI invocation, while the gateway independently performed provider credential
and model discovery. The workflow therefore mixed two separate concerns:
global provider discovery inside contextual-orchestrator and the virtual pool
requested by the GitHub Actions caller.

The current ContextualWisdomLab GitHub Actions contract separates those
concerns. GitHub Actions model-backed callers use the contextual-orchestrator
gateway and request exactly `orchestrator/free`; provider discovery, candidate
admission, ranking, serving, failover, and fallback remain contextual-
orchestrator responsibilities. Supplying `OPENAI_API_KEY` to gateway bootstrap
is not itself a free-pool defect: global discovery may include OpenAI models,
while `orchestrator/free` candidate admission must exclude OpenAI-derived
models and admit only independently eligible free-pool provider-account
sources. A GitHub Actions caller does not implement a second provider or model
selection policy.

`ContextualWisdomLab/.github` ADR-0003 records the central review-sidecar
contract and its 2026-09-02 correction: OpenCode, Noema, and Strix use
`orchestrator/free`; private targets additionally require ZDR admission. The
organization owner has also explicitly directed that contextual-orchestrator
models used by GitHub Actions are fixed to `orchestrator/free`.

This repository's hourly loop was therefore an observable caller-side
conformance gap. The gap is independent of whether `orchestrator/auto` remains
a valid general-purpose gateway pool for non-GitHub-Actions consumers.

## Decision

1. `.github/workflows/opencode-hourly-loop.yml` points OpenCode at
   `contextual_orchestrator_gateway/orchestrator/free` in the OpenCode config
   and CLI invocation. The local OpenCode catalog exposes only the matching
   `orchestrator/free` virtual model.
2. `--auto-discover-model-agents` remains enabled for contextual-orchestrator.
   Credential/model discovery is broader than caller pool selection and stays
   owned by the gateway. In particular, receiving all configured credential
   sources does not authorize every discovered model for the free pool.
3. No GitHub Actions exception to `orchestrator/free` is created here. A
   future GitHub Actions model-backed caller must remain on `orchestrator/free`;
   a missing required capability or eligible free candidate fails closed and
   is repaired in contextual-orchestrator rather than bypassed through
   `orchestrator/auto`, a direct provider identifier, a provider group, or a
   paid fallback.
4. `tests/test_hourly_opencode_loop_contract.py` requires the free virtual model
   and rejects both the qualified `orchestrator/auto` route and an
   `"orchestrator/auto":` catalog entry. It also verifies that gateway
   bootstrap continues to receive the configured credential environment names,
   including `OPENAI_API_KEY`, without turning those bootstrap inputs into a
   caller-side routing decision.
5. This ADR remains **Proposed** while its implementation PR is open. It may be
   changed to Accepted only after the protected default branch contains the
   decision and exact-head required evidence has completed under ordinary
   repository protection.

## Consequences

### Positive

- GitHub Actions has one explicit caller contract: contextual-orchestrator plus
  the `orchestrator/free` virtual pool. Leaf workflow configuration no longer
  decides provider/model/group/paid fallback.
- Global credential discovery remains compatible with the free-pool admission
  boundary. In particular, retaining `OPENAI_API_KEY` for global discovery does
  not authorize OpenAI-derived candidates for `orchestrator/free`.
- Private-repository ZDR enforcement remains a gateway admission requirement,
  not a leaf-side provider selection shortcut.

### Failure semantics

- A request that cannot obtain an eligible `orchestrator/free` candidate fails
  closed without a paid or direct-provider bypass.
- A `400 invalid_model` response is evidence of a fail-closed request state,
  not sufficient evidence for one specific root cause. Operators must preserve
  discovery/admission evidence and distinguish, for example, an actually empty
  eligible catalog from a provider discovery failure, credential-source
  omission, candidate-admission defect, or other contract failure. The workflow
  must not relabel that response as "free-catalog exhaustion" without the
  corresponding gateway evidence.
- Historical `docs/product-technical-gap-baseline.md` entries that describe the
  previous `orchestrator/auto` caller remain historical evidence; current
  behavior is determined from the protected workflow, this ADR after
  acceptance, and exact-head verification.

## Rejected alternatives

### Keep `orchestrator/auto` for the hourly GitHub Actions loop

Rejected because it conflicts with the current organization-wide GitHub Actions
caller contract. General gateway support for `orchestrator/auto` does not imply
that a GitHub Actions leaf may select it.

### Remove `OPENAI_API_KEY` from workflow bootstrap solely because the caller uses `orchestrator/free`

Rejected. Credential registration/global discovery and free-pool candidate
admission are separate contracts. The free-pool boundary belongs inside
contextual-orchestrator; removing a globally supported credential at the leaf
would hide rather than verify that boundary.

### Interpret any `400 invalid_model` as proof of free-catalog exhaustion

Rejected because the HTTP outcome does not identify that causal state by
itself. The workflow and operator must rely on gateway discovery/admission
provenance and fail closed when the cause is not identified.

## References

ContextualWisdomLab. (2026). *ADR-0003: Vendored contextual-orchestrator
review sidecar with governed gateway pools* [Architecture decision record,
amended 2026-09-02]. `ContextualWisdomLab/.github`,
`docs/adr/0003-contextual-orchestrator-vendored-free-zdr.md`.
https://github.com/ContextualWisdomLab/.github/blob/main/docs/adr/0003-contextual-orchestrator-vendored-free-zdr.md

ContextualWisdomLab. (2026). *Pin orchestrator-routed KG extraction to the
`orchestrator/free` pool* [Proposed architecture decision in
ContextualWisdomLab/naruon#1525]. https://github.com/ContextualWisdomLab/naruon/pull/1525
