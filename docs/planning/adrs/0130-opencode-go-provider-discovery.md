---
id: "0130"
title: "Add OpenCode Go as a second, subscription-gated provider source"
status: proposed
proposed_date: "2026-09-02"
deciders:
  - "repository maintainer"
affected_components:
  - "contextual_orchestrator/model_discovery.py"
  - "docs/kv-credentials.md"
related:
  - path: "docs/planning/adrs/0041-generalize-models-dev-cost-classification.md"
    relation: extends
success_criteria:
  - metric: "Go discoverable independently of Zen"
    target: "registering only OPENCODE_GO_API_KEY discovers opencode_go models; registering only OPENCODE_ZEN_API_KEY discovers opencode_zen models and never opencode_go"
    source: "tests/test_model_discovery.py::test_opencode_go_credential_missing_does_not_affect_opencode_zen_discovery"
  - metric: "fail-closed cost/modality join"
    target: "opencode_go joins the same 'opencode' Models.dev catalog as opencode_zen, under the same unmatched-id/missing-cost/fetch-failure fail-closed rules ADR 0041 already proved"
    source: "tests/test_model_discovery.py::test_opencode_go_joins_models_dev_cost_and_modalities_without_name_inference and test_opencode_go_metadata_failure_keeps_availability_but_not_free_suffix"
  - metric: "mixed-protocol safety"
    target: "only IDs documented for /v1/chat/completions enter the ordinary chat pool; /responses and /messages IDs are excluded until a protocol-specific adapter exists"
    source: "contextual_orchestrator/model_discovery.py::_OPENCODE_GO_CHAT_MODEL_IDS and tests/test_model_discovery.py::test_opencode_go_excludes_responses_and_messages_models_from_chat_pool"
---

# Add OpenCode Go as a second, subscription-gated provider source

## Context

`contextual_orchestrator/model_discovery.py` already discovers `opencode_zen`
(`https://opencode.ai/zen/v1/models`, `OPENCODE_ZEN_API_KEY`,
`bootstrap_required=False`, joined against Models.dev's `"opencode"` catalog
per ADR 0041/0032). A separate request asked whether "OpenCode Go" is a real,
distinct catalog reachable with the same kind of credential, or a
misremembered product name that should not be invented.

Verified against OpenCode's own docs and the `sst/opencode` source before
writing any code:

- `https://opencode.ai/docs/go/` documents OpenCode Go as a $10/month
  subscription with its own model list, its own base URLs
  (`https://opencode.ai/zen/go/v1/chat/completions`,
  `.../v1/messages`, `.../v1/responses`), and its own discovery endpoint,
  `https://opencode.ai/zen/go/v1/models` — a real, separate, programmatically
  discoverable catalog, not a documentation section or a language SDK.
- `https://opencode.ai/docs/zen/` cross-links "Go" as a distinct entry under
  its own "Usage" navigation, confirming Zen and Go are two products from the
  same vendor console, not two names for one thing.
- `packages/console/app/src/routes/zen/util/handler.ts` in `sst/opencode`
  (ground truth, not third-party commentary) shows Zen and Go share one
  Authorization-header validation path — the same API-key *format*
  authenticates both — and are distinguished purely by a `modelList: "full" |
  "lite"` catalog selection plus a separate `authInfo.billing.lite`
  subscription/entitlement check. Third-party write-ups (bitdoze.com,
  qcode.cc, deepwiki.com/sst/opencode) independently corroborate: Go exposes
  fewer models than Zen (a documented subset of the same id namespace — a
  Zen-only model on Go 404s), and reaching Go requires its own active
  subscription even when the key format matches Zen's.

So the premise holds with one refinement: "usable via the OpenCode API key"
is true of the *credential mechanism* (same header shape, same vendor
console), not of a single literal secret value automatically granting both —
a Zen key with no Go subscription does not unlock Go, matching how e.g. an
`OPENROUTER_API_KEY` without spend enabled already yields `spend_admitted =
False` in this same module rather than a hard failure.

## Decision

Add one more `ProviderModelSource` entry, `opencode_go`, immediately after
`opencode_zen` in `PROVIDER_MODEL_SOURCES`:

- `credential_name="OPENCODE_GO_API_KEY"` — a **separate** KV credential from
  `OPENCODE_ZEN_API_KEY`, even though both accept the same key format. This
  mirrors the existing `nvidia_nim` / `nvidia_nim_sub` precedent ("each...KV
  credential is an independent account boundary...even though both currently
  use the same API endpoint"): Go requires its own subscription/entitlement
  independent of Zen access, so collapsing the two onto one credential name
  would let a deployment with Zen-only access silently attempt (and fail) Go
  discovery, and would merge two logically distinct accounts under the
  per-account diagnostics in `_log_zero_free_serving_contribution`.
- `list_url="https://opencode.ai/zen/go/v1/models"`,
  `chat_base_url="https://opencode.ai/zen/go/v1"` — Go's own endpoints, not
  Zen's.
- `style` remains `"openai_compatible"` for the discovery envelope,
  but the source carries an explicit allowlist derived from Go's official
  endpoint table. Go's `/v1/models` response has the same shape as other
  OpenAI-compatible discovery responses, while its model IDs do not all share
  the same request protocol. Only the documented chat-completions subset enters
  the generic CO chat pool; responses/message models fail closed until a
  protocol-specific adapter is released.
- `bootstrap_required=False` — matches `opencode_zen`; most deployments will
  have neither, one, or the other, never both required.
- `models_dev_provider_id="opencode"` — the same value as `opencode_zen`.
  Go's model ids are a documented subset of Zen's own catalog under the
  identical id namespace, so ADR 0041's already-verified fail-closed join
  (`_merge_models_dev_metadata` / `_models_dev_cost_is_free`: exact-id match
  only, unmatched/missing/partial cost stays `is_free=False`) applies
  unchanged. `discover_all_models`'s single shared Models.dev fetch already
  covers any source with a registered credential and a
  `models_dev_provider_id`, so registering both Zen and Go still costs at
  most one `https://models.dev/api.json` fetch per discovery run.

## Consequences

- Operators can register `OPENCODE_GO_API_KEY` and get the same automatic
  discovery → agent-pool-candidate pipeline every other provider already
  gets, with no new code path to review or maintain.
- `docs/kv-credentials.md`'s provider table previously omitted `opencode_zen`
  entirely (a pre-existing gap, not introduced here) while double-counting
  the dynamically-built configured gateway as one of "six" providers; fixed
  alongside this addition so the table now lists all eight
  `PROVIDER_MODEL_SOURCES` entries plus the configured-gateway path,
  consistent with ADR 0041's own "six provider *sources*" framing (which
  already counted `opencode_zen` as one of the six, before this ADR's
  `opencode_go` became the seventh static source).
- Also corrected the same doc's stale claim that Bytez uses a `Key <token>`
  auth scheme; the code (`AUTH_SCHEME_RAW_TOKEN`,
  `orchestrator.format_authorization_header`) and the
  `CHANGELOG.d/bytez-raw-token-authorization.md` fragment already on `main`
  show Bytez actually takes a bare token with no scheme word — the docs table
  had not been updated to match that fix.
- Go models using `/v1/responses` or `/v1/messages` are deliberately not
  promoted to ordinary chat agents yet. This is a temporary capability boundary,
  not a claim that those endpoints are unsupported; a later protocol adapter
  must add explicit endpoint metadata and wire-format tests before admission.
- No change to any existing provider's behavior: `opencode_zen`'s source
  entry, credential, and tests are untouched.

## References

OpenCode. (2026). *Go*. https://opencode.ai/docs/go/

OpenCode. (2026). *Zen*. https://opencode.ai/docs/zen/

sst/opencode. (2026). `packages/console/app/src/routes/zen/util/handler.ts`.
https://github.com/sst/opencode

Docs.bytez.com. (2026). *List models*.
https://docs.bytez.com/http-reference/list/models.md
