# Actions bootstrap integration evidence (PR #1057)

The dated record below was relocated from
`docs/product-technical-gap-baseline.md` during the 2026-09-10 incident merge
so newer baseline entries could be preserved without a top-of-file conflict.
Its observations and test counts remain historical, not a fresh merged-head
result or a claim of deployed provider availability.

## 2026-09-04 autonomous commercialization loop: issue #1023 Actions bootstrap
integration proof

Observation time: 2026-09-04 Asia/Seoul.

GitHub authentication was re-verified first with `gh api user`. The primary
checkout was dirty, so this slice ran in clean worktree
`.worktrees/commercial-loop-20260904-issue1023` from current `origin/main`.
Open PR heads and prior `commercial-loop-*` worktrees were re-fetched before
editing. Two live `orchestrator/free` PRs were checked first:
[#1049](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/1049)
already carries the exact long-transport failover fix and is waiting on hosted
checks, while
[#993](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/993)
shows a current `noema-review` transport failure on the same boundary. Copying
that fix into another branch would have duplicated an active PR contract, so
this invocation advanced the next independent owner gap instead.

### Completed root-cause unit

Issue [#1023](https://github.com/ContextualWisdomLab/contextual-orchestrator/issues/1023)
requires proof that a GitHub Actions consumer can start the owner gateway from
the documented bootstrap interface alone, with provider credentials staying
inside contextual-orchestrator ownership.

The new integration regression extends `tests/test_ci_gateway_bootstrap.py`
from seed-only unit coverage to the real Actions-facing startup path:

- `scripts/ci/serve_seeded_gateway.py` seeds provider and gateway credentials
  into the process-local KV and removes them from `os.environ`;
- `contextual_orchestrator.__main__.main()` is executed with the same
  `--serve`, `--auto-discover-model-agents`, and `--auth-token-key
  CONTEXTUAL_ORCHESTRATOR_TOKEN` interface the hourly workflow documents;
- the test serves real HTTP, verifies authenticated `GET /v1/models` exposes
  `orchestrator/free`, and verifies authenticated `POST /v1/chat/completions`
  with `model="orchestrator/free"` succeeds through owner-side routing;
- the routed free-model request now intercepts the real HTTPS provider
  transport instead of short-circuiting through `mock://`, so the gateway must
  resolve `OPENROUTER_API_KEY` from the KV and send
  `Authorization: Bearer router-secret` on the provider request before the
  success path can pass;
- the same two endpoints now also prove both missing and invalid Bearer tokens
  fail with the documented `401 unauthorized` contract before any owner-route
  success is accepted;
- a second regression proves the same bootstrap path fails closed when
  discovery exposes only paid chat candidates: `orchestrator/free` is omitted
  from `/v1/models`, the same authenticated chat request returns
  `400 invalid_model`, and no paid/provider-specific bypass is taken;
- the wire-visible responses stay secret-safe: no provider credential names,
  credential values, exact configured `chat_base_url` strings, or `mock://`
  transport internals are exposed.

This does not complete issue `#1023`'s full immutable-release, provenance, or
short-lived-auth scope. It closes one smaller owner-boundary proof that a
consumer does not need direct provider routing logic just to reach the owner
gateway's authenticated free pool.

### Exact local verification

- `uv run pytest tests/test_ci_gateway_bootstrap.py -q`
  -> `3 passed in 1.60s`
