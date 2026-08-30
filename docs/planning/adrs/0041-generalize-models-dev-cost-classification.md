---
id: "0041"
title: "Generalize the Models.dev cost join beyond OpenCode Zen"
status: accepted
proposed_date: "2026-08-30"
accepted_date: "2026-08-30"
deciders:
  - "repository maintainer"
affected_components:
  - "contextual_orchestrator/model_discovery.py"
related:
  - path: "docs/planning/adrs/0032-model-group-cost-aware-discovery.md"
    relation: extends
success_criteria:
  - metric: "orchestrator/free coverage"
    target: "nvidia_nim and nvidia_nim_sub contribute Models.dev-verified free models to the zero-cost pool, not only opencode_zen"
    source: "tests/test_model_discovery.py::test_nvidia_nim_joins_models_dev_cost_and_modalities_without_name_inference"
  - metric: "fail-closed classification"
    target: "an unmatched model id, a missing/partial cost object, a nonzero cache_read/cache_write-only vector, or a Models.dev fetch failure all leave is_free False"
    source: "tests/test_model_discovery.py::test_nvidia_nim_metadata_failure_keeps_availability_but_not_free and the cache-fee/unmatched cases in the joins test"
  - metric: "one fetch, not four"
    target: "discover_all_models fetches https://models.dev/api.json at most once per call regardless of how many registered sources want it"
    source: "tests/test_model_discovery.py::test_discover_all_models_fetches_models_dev_exactly_once_across_sources"
---

# Generalize the Models.dev cost join beyond OpenCode Zen

## Context

`orchestrator/free` (ADR 0032) admits only models carrying discovery's
explicit `cost:free` evidence. `DiscoveredModel.is_free` is set once, at parse
time, in `_parse_openai_compatible` (`_pricing_is_free`, unless a merged row
already carries an explicit `is_free` boolean), which requires a provider's
own model-list response to carry a real per-token price of exactly zero. Of this
gateway's five configured provider sources, only OpenRouter's own API ever
reports real pricing, and OpenRouter is deliberately `evidence_only=True`
(commit `952996ec`, a ZDR-privacy hardening that stays untouched) and so never
serves inference. `openai`, `nvidia_nim`, `nvidia_nim_sub`, and `bytez` never
report pricing in their own `/v1/models` responses, so `is_free` was never
`True` for any of them. `orchestrator/free` was therefore structurally empty
in practice: the one provider ADR 0032 already cross-references against
Models.dev to recover a price signal, OpenCode Zen, is `bootstrap_required =
False` and not always registered, leaving the pool with no reliable member.

ADR 0032 already solved exactly this gap for OpenCode Zen: intersect its
`/zen/v1/models` availability response with the `opencode` catalog in
Models.dev (`https://models.dev/api.json`), which OpenCode's own docs name as
the source of its catalog. That join lived as one hardcoded branch in
`discover_provider_models` (`if source.provider_name == "opencode_zen": ...`)
against one hardcoded provider-id constant. ADR 0032 names this the intended
extension point: "This source/effective-state split is the contract for
adding further providers."

Re-verified live on 2026-08-30 against `https://models.dev/api.json`
(4,432,167 bytes, 211 providers, 7,488 models total):

- `nvidia` is a real Models.dev provider entry (`api:
  https://integrate.api.nvidia.com/v1`, matching NVIDIA NIM's own base URL),
  with 103 models under the exact same `vendor/model` id shape NIM's own
  `/v1/models` returns — `meta/llama-3.1-8b-instruct` is present in both. 99
  of those 103 carry an all-zero cost vector; 4 are genuinely paid
  (`nvidia/nemotron-3-super-120b-a12b`, `nvidia/nemotron-3-ultra-550b-a55b`,
  `deepseek-ai/deepseek-v4-flash`, `deepseek-ai/deepseek-v4-pro`).
- `openai` is a real Models.dev provider entry (47 models, bare model-id
  keys). Every model with a usable `cost` object has at least one nonzero
  component today (43 of 47; the remaining 4 are image models with no `cost`
  field at all) — OpenAI has no free chat models, so this signal correctly
  contributes nothing to `orchestrator/free` right now. Should that ever
  change, the same fail-closed join self-corrects with no code change.
- `bytez` has **zero** coverage anywhere in the Models.dev payload (a full
  key/substring scan over all 211 provider ids finds no match). Bytez's own
  docs (docs.bytez.com/model-api/docs/billing) describe billing only in
  prose — account-level credit, not a per-model price field — so there is
  genuinely no machine-fetchable free/paid signal for Bytez to join against.
  `nvidia_nim_sub` shares NIM's exact upstream catalog under a second KV
  credential (existing code comment above `PROVIDER_MODEL_SOURCES`), so it
  joins against the identical `nvidia` Models.dev entry as `nvidia_nim`.

## Decision

Move the provider-id used for the Models.dev join from a hardcoded branch to
declared configuration. `ProviderModelSource` gains
`models_dev_provider_id: str | None = None`. `opencode_zen` sets it to
`"opencode"` (replacing the deleted `_MODELS_DEV_OPENCODE_PROVIDER` module
constant and its `provider_name == "opencode_zen"` special case with the same
value, now expressed as data), `nvidia_nim` and `nvidia_nim_sub` both set it
to `"nvidia"`, and `openai` sets it to `"openai"`. `openrouter` and `bytez`
keep the `None` default: OpenRouter already reports its own real per-token
pricing and stays `evidence_only=True` regardless, and there is no
Models.dev signal to join for Bytez.

The invocation site in `discover_provider_models` becomes `if
source.models_dev_provider_id: ... _merge_models_dev_metadata(payload,
metadata, source.models_dev_provider_id)`. `_merge_models_dev_metadata` and
`_models_dev_cost_is_free` are unchanged: they were already generic over an
arbitrary provider-id string. This is a surgical generalization of one call
site, not new classification logic.

`discover_all_models` now fetches `https://models.dev/api.json` at most once
per call — before its per-source loop, only when at least one source in the
requested tuple both declares a `models_dev_provider_id` and has a credential
registered — and hands every source the identical parsed payload object
through a new `models_dev_metadata` keyword parameter on
`discover_provider_models`. That parameter defaults to a private sentinel
(`_NOT_FETCHED`, not `None`) so a genuine fetch failure — which honestly
produces `None` — stays distinguishable from "no shared payload was
supplied, fetch it yourself." Every existing direct caller of
`discover_provider_models`, tests included, keeps its lazy per-call
fetch-on-demand behavior unchanged; only `discover_all_models` opts into the
shared fetch. `nvidia_nim` and `nvidia_nim_sub` therefore join against the
same in-memory Models.dev payload rather than fetching it twice.

### Cost-safety argument

`_merge_models_dev_metadata` and `_models_dev_cost_is_free` are unchanged.
For a matched row (its `id` is present in Models.dev's `models` map for the
joined provider id), the enriched row's `is_free` is set *solely* from
`_models_dev_cost_is_free(cost)` against the independently-fetched Models.dev
catalog — the provider's own listing carries no per-model price for these
four providers today, so there is nothing on the provider side for a
compromised or lying upstream to assert instead; classification rests on
third-party evidence, not self-report. `_models_dev_cost_is_free` classifies
a model free only when its Models.dev `cost` object is present, non-empty,
and every monetary component present anywhere in it — `input`, `output`,
`cache_read`, `cache_write`, or any other numeric leaf — is a valid,
non-negative, exactly-zero number; one nonzero component anywhere fails the
whole model closed. The join itself is an **exact `model_id` string match**
against Models.dev's `models` map; there is no fuzzy, prefix, or suffix
matching, so a model missing from Models.dev, or present under a different
id, cannot inherit another model's price (consistent with ADR 0032's
"model-name suffixes are never treated as price evidence"). An unmatched row
is passed through untouched by the merge — it is not marked free by this
join. A Models.dev fetch failure
(`URLError`/`TimeoutError`/`ValueError`/`OSError`) degrades `metadata` to
`None`; `_merge_models_dev_metadata` then returns the untouched availability
payload, so cost stays unknown rather than free. Generalizing the call site
to four provider ids cannot enlarge any of these invariants — it only
changes which provider-id string is looked up in the same already-verified
matching and classification code. Every registered failure mode (unmatched
id, missing entry, partial cost object, a cache-only nonzero component, a
fetch failure) therefore still leaves `is_free = False`; nothing this change
touches can turn a paid model free.

## Consequences

- `orchestrator/free` regains real member coverage: `nvidia_nim` and
  `nvidia_nim_sub` can now contribute Models.dev-verified free models,
  instead of the pool depending entirely on whether `opencode_zen` happens to
  be registered.
- `bytez` remains a permanent, documented gap — not a TODO — until Bytez
  publishes a machine-fetchable per-model price signal.
- `openai` contributes nothing to the free pool today, by design, and will
  self-correct with no code change if OpenAI ever lists a genuinely free
  chat model in Models.dev.
- `discover_all_models` makes one additional outbound HTTPS request in the
  common case where any of `opencode_zen`/`nvidia_nim`/`nvidia_nim_sub`/
  `openai` are registered, in exchange for removing what would otherwise be
  up to three redundant identical fetches.

## References

Models.dev. (2026). *Models.dev API*. https://models.dev/api.json

OpenCode. (2026). *Zen*. https://opencode.ai/docs/zen

NVIDIA. (2026). *NVIDIA NIM APIs*. https://docs.api.nvidia.com/nim/

OpenAI. (2026). *Models*. https://platform.openai.com/docs/models

Bytez. (2026). *Billing*. https://docs.bytez.com/model-api/docs/billing
