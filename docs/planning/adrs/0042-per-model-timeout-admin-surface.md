---
id: "0042"
title: "Per-model LLM request timeout: admin-editable override, audited, inherited"
status: accepted
proposed_date: "2026-09-02"
accepted_date: "2026-09-02"
deciders:
  - "repository maintainer"
affected_components:
  - "contextual_orchestrator/orchestrator.py"
  - "contextual_orchestrator/server.py"
  - "contextual_orchestrator/api_contract.py"
  - "contextual_orchestrator/admin.py"
related:
  - path: "docs/planning/adrs/0033-admin-console-ui-tooling-boundary.md"
    relation: informational
success_criteria:
  - metric: "operator can view/set/clear per-model timeout"
    target: "GET/PATCH/DELETE /api/v1/model_timeouts(/{model}) and a Settings-view panel in admin.py all round-trip"
    source: "tests/test_model_timeouts.py"
  - metric: "an override changes real outbound call behavior, not just stored config"
    target: "ModelClient.chat/stream_chat pass the resolved per-model timeout into _send_with_retry/_stream_send -> _open_provider"
    source: "tests/test_model_timeouts.py::test_chat_call_uses_the_resolved_per_model_timeout, ::test_stream_chat_uses_the_resolved_per_model_timeout"
  - metric: "no override leaves every existing caller's exact prior call shape unchanged"
    target: "the resolver wired into ModelClient returns None (not the resolved default) absent an override, so call sites omit the timeout kwarg entirely in the common case"
    source: "tests/test_model_timeouts.py::test_wired_resolver_returns_none_for_a_model_with_no_override, ::test_bare_model_client_with_no_resolver_passes_no_timeout_override"
---

# Per-model LLM request timeout: admin-editable override, audited, inherited

## Context

`docs/product-goal-directive.md` (`ContextualWisdomLab/.github`) §8 and this
repo's own product directive record a standing requirement: an admin web
where operators can view/set/clear/restore per-model LLM timeouts, with
units, priority/inheritance, input validation, audit history, and an API
contract. Before this change, `ModelClient.timeout` (default 90s) was one
flat instance attribute applied to every outbound call regardless of
model — there was no per-model override anywhere in the codebase (verified
by direct search: no `model_timeout`, no per-model timeout registry, no
admin endpoint for it), and no way to change it without restarting the
process with a different constructor argument.

This repository already has two proven KV-config seams for exactly this
shape of admin-editable, audited, operator-facing state:
`credentials.py`/`kv_config.py` (secrets/config KV) and the
`model_group`/`list_model_groups`/`set_model_group`/`delete_model_group`
family on `TaskOrchestrator` (a live, admin-editable registry with GET
list/detail + PATCH/POST/DELETE HTTP routes, backed by `_StateStore`, with
`_append_audit_event` recording every change). This ADR follows the
model-group pattern rather than inventing a new one.

The `/admin` operator console (`admin.py`) already exists as ADR-0033
records: a deliberate, current, inline-stdlib-HTML console (eight
Figma-grounded frames), with React/Storybook explicitly deferred until one
of three concrete triggers is met. This feature does not meet any of those
triggers (it adds one panel to the existing Settings view, not a second
screen family, not a second consuming repository, not a new
component-based frontend) — so it extends `admin.py` in place, consistent
with ADR-0033, and does **not** touch the unbuilt `admin_ui/` scaffold
(ADR-0036, superseded).

## Decision

1. **Storage**: `TaskOrchestrator._model_timeout_overrides: dict[str, float]`
   (model name → seconds), persisted via a new `"model_timeout_override"`
   keyed kind in `_StateStore` (added to `_KEYED`; a new `_StateStore.delete`
   method supports clearing an override with no replacement — the existing
   `save()` only supported upsert for keyed kinds). Absent `state_db`, this
   is in-memory only, same as every other orchestrator registry.
2. **Inheritance**: `effective_model_timeout(model)` returns the override if
   set, else `float(self.client.timeout)` — the existing flat default is
   the "default" every override is described relative to; no new,
   independent default constant was introduced. `MIN_MODEL_TIMEOUT_SECONDS
   = 1.0` / `MAX_MODEL_TIMEOUT_SECONDS = 14400.0` bound valid overrides
   (`_validate_model_timeout_seconds`); the 14400s ceiling is not an
   invented round number — it matches the org's own already-evidenced
   `NOEMA_LLM_TIMEOUT_SECONDS` precedent
   (`docs/product-technical-gap-baseline.md`), and is consistent with
   `.github`'s recent removal of a 300s `LLM_TIMEOUT` cap on Strix (this
   org has been moving away from short hard caps on LLM call timeouts, not
   toward them).
3. **CRUD**: `list_model_timeouts`/`get_model_timeout` (+ recent
   set/clear audit history)/`set_model_timeout`/`clear_model_timeout` on
   `TaskOrchestrator`, mirroring `list_model_groups`/`get_model_group`/
   `set_model_group`/`delete_model_group` exactly (KeyError for an unknown
   model, ValueError for an invalid value, `_append_audit_event` on every
   write). No new audit mechanism — `model_timeout_set`/
   `model_timeout_cleared` events flow through the existing
   `list_recent_audit_events`/`/admin/state` surface the console already
   renders.
4. **API**: `GET /api/v1/model_timeouts`, `GET`/`PATCH`/`DELETE
   /api/v1/model_timeouts/{model}` — `PATCH` (not `PUT`) to match this
   repo's existing convention for "update" routes (`model_groups` uses
   `PATCH`, and there is no `do_PUT` handler in `server.py` at all; adding
   one would be a new routing mechanism for no reason). Declared in
   `api_contract.py`'s `OPENAPI_SPEC` the same way as every other
   `/api/v1/*` resource.
5. **Real enforcement, not inert config**: `ModelClient` gained a
   `model_timeout_resolver: Callable[[str], float] | None` attribute
   (default `None`, preserving every existing caller's behavior exactly).
   `TaskOrchestrator.__init__` wires it to `self._model_timeout_override_for`
   — **not** `effective_model_timeout`. The wired resolver returns `None`
   when no override exists (only a concrete value when one does), so
   `chat()`/`stream_chat()` can keep passing `_send_with_retry`/
   `_stream_send` **no** `timeout` kwarg at all in the common case,
   identical to the pre-existing call shape — an override only ever adds
   an explicit `timeout=` where one previously would not have appeared.
   (`effective_model_timeout`, which always resolves a concrete value, is
   for admin-facing display only — `list_model_timeouts`/
   `get_model_timeout`'s `effective_timeout_seconds` field — not for the
   resolver.) `_open_provider`/`_send_with_retry` already accepted an
   optional per-call `timeout` end-to-end (used by explicit readiness
   probes); this reuses that existing plumbing rather than adding a
   second one. `_stream_send` gained the same optional `timeout` parameter
   for parity on the streaming path.
6. **UI**: one new panel ("Model timeouts") added to `admin.py`'s existing
   Settings view — a table of every configured model's effective
   timeout/source, an inline input + Save/Restore-default per row, bilingual
   (en/ko) translations added alongside the existing `model_groups_title`
   block, following the exact `renderModelGroups`/`refreshModelGroups`/
   `saveModelGroup` pattern already in `admin.py`. Every insertion is
   additive (no existing line changed), so `tests/test_admin_contract.py`'s
   100+ exact-string assertions keep passing unmodified.

## Consequences

- Every existing test that monkeypatches `ModelClient._send_with_retry`/
  `_stream_send` with a fixed positional-only stand-in keeps working
  unchanged in the no-override case, because the resolver returns `None`
  and the call sites omit the kwarg — this was verified the hard way: an
  earlier version of this change always resolved and passed a concrete
  timeout, which broke `tests/test_mixed_pool_role_effort_selection.py`,
  `tests/test_telemetry.py`, and `tests/test_tool_execution_fallback.py`'s
  strict-signature test doubles; the fix was changing the resolver's
  semantics (return `None` absent an override), not patching every test
  double, which is both the smaller diff and the more correct design (an
  override is something that changes behavior only when an operator
  actually asked for one).
- `_stream_send`'s per-call timeout is computed **inside** its `try:`
  block (matching where the equivalent `_open_provider` call already sat
  before this change) — moving it outside, even transiently during
  development, silently let a real provider `HTTPError` escape the
  reclassification logic that turns it into a package-owned
  `ProviderUpstreamError`; `tests/test_true_streaming.py`'s existing
  regression test for that reclassification caught it.
- Not yet wired: the batch/embeddings/rerank/transcription/image transport
  paths still use the flat `self.client.timeout` only. The chat and
  streaming-chat paths (the two used by `route()`/`conduct()`, the primary
  request path this feature's product requirement is about) are the ones
  wired. Extending the resolver to the remaining transport methods is
  straightforward (same `_resolve_timeout(agent)` call, same `if timeout
  is None` branch already used twice) but is left for a follow-up rather
  than touching every one of `ModelClient`'s many transport methods in one
  PR.
- No Keyverse SSO wiring in this PR. The admin console's session model
  (`/admin/session`, a shared bearer token) is unchanged. Gating `/admin`
  behind Keyverse OIDC SSO instead is a genuine cross-repo integration
  (see the sibling research this PR's description links) and is
  explicitly out of scope here.
