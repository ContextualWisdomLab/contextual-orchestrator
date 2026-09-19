# ADR 0123: Web-search tool and the MCP/A2A gateway foundation

## Status

Partially accepted. The web-search tool (Decision §1) is implemented in this
change. The MCP gateway, A2A gateway, and Camoufox-browsing pieces (Decision
§2-4) are design-only: recorded here so the bounded contexts, their
boundaries, and their sequencing are reconstructable, not implemented yet.

## Context

The product owner asked for contextual-orchestrator to become an **MCP
Gateway** and an **A2A Gateway**, so internal agents (Strix, Noema) can search
the web on another agent's behalf, decide when external search is needed, and
verify claims via search — "a Perplexity-search-like emulation" for Strix, a
"Web Search Tool" for Noema — backed by SearXNG plus other self-hostable
metasearch engines, with Camoufox for the actual browsing, isolated via
`ContextualWisdomLab/quarantine-sandbox-runtime`.

That is four distinct pieces wearing one request:

1. A **web-search tool**: the actual product capability an agent calls to get
   grounded, citable results. This is the payload.
2. An **MCP Gateway** role: contextual-orchestrator exposing and/or proxying
   Model Context Protocol tool calls, so tool access is centralized the way
   model routing already is.
3. An **A2A Gateway** role: contextual-orchestrator brokering Agent2Agent
   calls between internal agents (one agent asking another to run a
   sub-task, e.g. a search, on its behalf).
4. **Camoufox browsing + session isolation**: rendering a specific page (not
   search results) for JS-heavy verification targets, run inside an isolated
   sandbox rather than directly on the orchestrator process.

None of these currently exist as such in this repository. What *does* exist,
found while scoping this ADR:

- **"Tool calling" is already a discovered model *capability*, not an MCP
  role.** `chat_capability.py` / `model_discovery.py` detect whether a
  provider's chat-completions endpoint accepts an OpenAI-style `tools`
  array. That is per-model tool-calling passthrough — orthogonal to whether
  contextual-orchestrator itself speaks the Model Context Protocol as a
  server or client. `tool_fallback.py` classifies failures from that same
  passthrough path (`ToolFailureKind`, `ToolFallbackAction`); it is not an
  MCP implementation either.
- **contextual-orchestrator already consumes one MCP server as a client**,
  today: `privacy_policy_analysis._render_policy_document_with_camoufox`
  uses the official `mcp` Python SDK (`mcp.Client`,
  `mcp.client.streamable_http.streamable_http_client`) to call a
  `camofox-mcp` server's `create_tab` / `camofox_get_page_html` / `close_tab`
  tools, for exactly one narrow purpose: rendering a JS-heavy provider
  privacy-policy page during zero-data-retention (ZDR) discovery. This is a
  real, reviewed, tested MCP *client* integration — but scoped to one
  document type, not a general gateway.
- **Camoufox session isolation already ships, via Wardnet, not
  `quarantine-sandbox-runtime`.** `compose.camoufox-wardnet.yaml` deploys
  `wardnet` (DNS-pinned egress + authenticated CONNECT proxy),
  `camofox-browser` (`ghcr.io/redf0x1/camofox-browser`, pinned by digest),
  and `camofox-mcp` (`ghcr.io/redf0x1/camofox-mcp`, pinned by digest,
  Streamable HTTP transport) on isolated Docker networks with no published
  ports; the browser's only route out is through Wardnet. `docs/kv-credentials.md`
  documents the full boundary. This is a working, deployed answer to "isolate
  the browser's network egress" — just not the answer the request named.
- **`quarantine-sandbox-runtime` is not ready to receive this feature.**
  Verified live: `develop` is a stub; real work is an unmerged Draft PR stack
  (`ContextualWisdomLab/quarantine-sandbox-runtime#1` → `#6` → `#9` → `#10` →
  `#13`, all open); the crate has no HTTP/CLI entrypoint or container backend,
  only a Rust library with a newly added `CommandExecutionBackend` contract
  not yet wired to anything real; real container isolation is externally
  blocked on `ContextualWisdomLab/.github#1590` (no LSM-capable CI runner).
  Per `docs/CWL-MASTER-CONTEXT.md` §3/§6, this crate is also the "noema
  quarantine sandbox" referenced across the ecosystem UML (`WARD -->|"quarantine
  detonation"| NOEMA`, `NOEMA --> ORCH`) — a general-purpose sandboxed-execution
  primitive meant to serve *multiple* consumers (AI-SOC artifact detonation,
  noema's do-anything agent, and, per this request, Camoufox browsing), not a
  bespoke browser sandbox.
- **No duplicate work found.** `gh pr list --repo ContextualWisdomLab/contextual-orchestrator
  --state open --search "mcp OR a2a OR search OR searxng OR camoufox"` and a
  repo-wide grep for `mcp`, `a2a`, `searxng`, `web_search`, `perplexity` found
  no open PR and no existing product code for this capability. The only
  `web_search` hits are `server.py`'s honesty gate
  (`_validate_chat_audio_web_search_surface`), which *rejects* a caller-supplied
  OpenAI-style `web_search_options` parameter on chat/completions with a named
  migration error, because contextual-orchestrator does not (and after this
  change, still does not) claim to support that passthrough parameter. This
  ADR's `web_search()` is an unrelated, explicitly-invoked library call, not a
  chat-completions parameter — it must not be wired into that passthrough
  surface, or the honesty tests (`tests/test_chat_audio_web_search_reject_http_honesty.py`
  and siblings) start lying.
- `.github`'s `opencode.jsonc` already gives OpenCode Review its own MCP
  servers (Context7, DeepWiki, web-search) resolved by OpenCode's own
  harness, independent of contextual-orchestrator. That is why this request
  is "add this org-wide, including to Noema and Strix" rather than
  duplicating what OpenCode already has for itself: Noema and Strix have no
  such harness.

## Decision

### 1. Web-search tool (implemented this change)

`contextual_orchestrator/web_search.py` adds `web_search(query, ...) ->
list[WebSearchResult]`, backed by a SearXNG-compatible instance's JSON API
(`GET /search?format=json`). Configuration is KV-credential-based
(`SEARXNG_URL`, optional `SEARXNG_TOKEN`), matching every other provider
secret in this repository — see `docs/kv-credentials.md`. It reuses
`ModelClient._validate_provider` / `ModelClient._open_provider` purely as a
generic SSRF-safe HTTP boundary, exactly as `crawl_policy_document` already
does for Wardnet; it does not add a new HTTP client dependency or a second
hand-rolled egress check. This module does not deploy SearXNG — the
project's own Docker Compose deployment is documented upstream
(SearXNG Authors, n.d.).

Engine research (full table: `docs/library_research.md`, "Web search /
metasearch client"):

- **SearXNG** (AGPL-3.0) — implemented. A federated metasearch aggregator
  with a documented JSON API (SearXNG Authors, n.d.).
- **Whoogle** (MIT) — evaluated and rejected. Archived 2026-08-14; Google
  closed the scraping workaround it depended on in 2024, and the maintainer
  states search no longer functions. A permissive license does not offset a
  dead upstream.
- **YaCy** (GPL-2.0-or-later) — evaluated, documented as the next self-hosted
  engine to add. Architecturally different from SearXNG: its own crawled P2P
  index rather than federated results, with a built-in JSON/XML API. Not
  implemented this slice for lack of a deployment to test against.
- **Brave Search API** (commercial) — documented as the fallback if
  self-hosted coverage/quality proves insufficient later. Not implemented; no
  product requirement to pay for search yet.

`SUPPORTED_ENGINES` is a one-tuple today; adding a second engine is a new
entry plus a request-building function, not a redesign.

### 2. MCP Gateway — design only, not built

An MCP role is two separable things, and the honest answer is contextual-orchestrator
eventually needs **both**, sequenced by actual need:

- **MCP server role** (contextual-orchestrator exposes tools; Strix/Noema
  call it): higher priority. Strix and Noema have no MCP-resolving harness of
  their own (unlike OpenCode Review, which resolves `opencode.jsonc`'s MCP
  servers directly). This is the natural home for `web_search()` — expose it
  as one MCP tool (`web_search`) once there is a concrete Strix/Noema caller
  wired up to use it, using the official `mcp` Python SDK's server
  primitives (already a dependency for the Camoufox MCP client path; the
  server side is new).
- **MCP client/proxy role** (contextual-orchestrator forwards to upstream MCP
  servers on a caller's behalf): lower priority, and partially already exists
  in miniature — `privacy_policy_analysis.py`'s Camoufox MCP client. A
  general proxy role (any upstream MCP server, any caller) is not needed
  until a second, materially different upstream MCP server shows up with a
  real consumer; building it against zero live consumers would be
  speculative plumbing (see Aggregate/Domain Service note below).

Not built this iteration. Sequencing: server role first, once a Strix or
Noema caller is ready to consume `web_search()` through it.

### 3. A2A Gateway — design only, not built

When built, conform to the official Agent2Agent protocol's Agent Card
discovery and task-delegation semantics (Linux Foundation, n.d.) rather than
inventing a bespoke internal protocol — this bounded context has a
Conformist relationship to an externally-owned standard, the same way the
MCP Gateway Context must conform to the Model Context Protocol spec
(Model Context Protocol, n.d.). contextual-orchestrator would act as the A2A
server that Noema and Strix discover and call, reusing the existing
KV-credential pattern for any per-agent authentication.

Not built this iteration; there is no concrete two-agent delegation caller
yet ("agent A asks agent B to search on its behalf" has no real A or B wired
up today). Building A2A transport plumbing before a real caller exists is the
kind of speculative abstraction this repository's own engineering
conventions reject. This needs its own follow-up ADR once a concrete use
case exists.

### 4. Camoufox browsing + session isolation — explicitly deferred

Camoufox (MPL-2.0; Playwright-API-compatible Firefox fork; no official MCP
server — `camofox-mcp` is a third-party wrapper, already pinned by digest in
this repo) already has session isolation shipped for one purpose, via
Wardnet, not `quarantine-sandbox-runtime`. Two paths were considered:

- **(a) Extend the existing Wardnet+Camoufox-MCP boundary** to a general
  "render this URL" capability for web-search fact-checking, reusing
  `_render_policy_document_with_camoufox`'s pattern with a wider URL scope
  than "provider privacy policy." Zero new isolation risk — it is the same
  reviewed, deployed boundary.
- **(b) Wait for and switch to `quarantine-sandbox-runtime`**, per the
  original request, once it has a real HTTP/CLI surface and its blocking
  issue (`ContextualWisdomLab/.github#1590`) is resolved.

**The call:** (a) now is not taken in this change — no browsing code ships
here — but is recorded as the recommended path when browsing *is* built,
because it reuses infrastructure that already passed review and is already
deployed, and it solves the actual stated problem (network-level isolation
for a browser process) that was being asked for. `quarantine-sandbox-runtime`
remains the target for the *other* things it is meant to serve — arbitrary
agent-authored code execution, AI-SOC artifact detonation — and the
migration path is: once it ships a real `CommandExecutionBackend`-backed
HTTP/CLI surface, Camoufox's *container* placement can move behind it while
keeping Wardnet as the network-egress control (the two are complementary
controls today, not substitutes — see `docs/kv-credentials.md`). This is
recorded as a decision, not a question, per this repository's "make the call
and proceed" convention; it is reversible in a follow-up ADR if the product
owner disagrees.

Not built this iteration, in either form.

## Domain-Driven Design (per `docs/product-goal-directive.md` §5)

### Subdomain classification

- **Core subdomain**: cost-aware, measured LLM routing (`orchestrator.py`,
  `model_discovery.py`, `cost_router.py`) — unchanged by this ADR.
- **Supporting subdomain**: grounded web-search retrieval (this ADR). It
  exists to give agents fresh, citable evidence; it is not itself
  contextual-orchestrator's differentiating IP, but the core routing mission
  is incomplete without it once agents need to reach beyond a model's
  training data.
- **Generic subdomain**: SSRF-safe HTTP egress validation
  (`ModelClient._validate_provider` / `_open_provider`). Already solved and
  reused, not reinvented, exactly as DDD recommends for generic subdomains.

### Bounded Contexts

- **Web Search Context** (new, this ADR): owns `WebSearchResult`, the
  SearXNG(-compatible) client, and search-engine credential configuration.
- **Provider Routing Context** (existing, `orchestrator.py`): owns
  `ModelAgent`, `ModelClient`, `TaskOrchestrator` — the LLM chat-completions
  routing core. Web Search Context depends on a small, explicit slice of it
  (see Shared Kernel below); it does not depend on chat/completions
  semantics.
- **Privacy Policy Analysis Context** (existing, `privacy_policy_analysis.py`):
  owns `PrivacyPolicyAssessment` and ZDR-evidence crawling. Reuses the same
  generic transport as Web Search Context but is a different bounded context
  — compliance evidence, not search grounding — and must not be merged with
  it even though both currently call SearXNG-shaped or Wardnet-shaped JSON
  APIs.
- **MCP Gateway Context** (future, not yet built): would own the MCP
  server/client surface and the catalog of tools it exposes or proxies.
- **A2A Gateway Context** (future, not yet built): would own Agent Card
  discovery and task-delegation state between internal agents.
- **Camoufox Browsing Context** (future, not yet built as a general
  capability): would own "render this URL and return content," distinct from
  Web Search Context's "search for this query and return result rows."

### Context Map

- Web Search Context —*Anti-Corruption Layer*→ SearXNG (external sidecar
  service): `_parse_results` translates SearXNG's foreign JSON schema into
  the stable `WebSearchResult` value object, so a SearXNG schema change (or a
  second engine's differently-shaped JSON) cannot leak into callers.
- Web Search Context —*Shared Kernel (minimal, deliberate)*→ Provider Routing
  Context: reuses only `ModelClient._validate_provider` /
  `ModelClient._open_provider`, not the full chat-completions surface. Kept
  intentionally small per this org's "minimize Shared Kernel" convention.
- MCP Gateway Context —*Conformist*→ Model Context Protocol specification
  (Model Context Protocol, n.d.): must track the external spec, not diverge
  from it.
- A2A Gateway Context —*Conformist*→ Agent2Agent protocol specification
  (Linux Foundation, n.d.): same relationship, different external standard.
- MCP Gateway Context —*Customer*→ Web Search Context (future): once built,
  the gateway exposes `web_search()` as one MCP tool among others; Web Search
  Context has no dependency back on the gateway.
- Camoufox Browsing Context —*Anti-Corruption Layer (existing, reviewed)*→
  third-party Camoufox MCP wrapper, via Wardnet: the exact pattern
  `privacy_policy_analysis.py` already uses, to be reused rather than
  duplicated.
- Camoufox Browsing Context —*Open Host Service (future)*→
  `quarantine-sandbox-runtime`'s `CommandExecutionBackend` contract, once it
  ships a real HTTP/CLI surface (see Decision §4).

### Ubiquitous Language

- **web search** — a query against one configured metasearch *engine*,
  returning bounded `WebSearchResult` rows. Never means rendering/browsing a
  specific URL (that is Camoufox Browsing Context's job).
- **grounding** — using a `WebSearchResult`'s `url`/`content` as citable
  evidence for a claim. This ADR ships retrieval only; deciding whether
  evidence supports or refutes a claim is a separate, unbuilt judge/verifier
  concern, not conflated here.
- **engine** — one metasearch backend implementation (`searxng` today, `yacy`
  documented as next). Never a model provider — `ModelAgent`/`model_group`
  already own that term in Provider Routing Context.
- **MCP Gateway** — contextual-orchestrator acting as a Model Context
  Protocol server and/or client/proxy. Explicitly distinct from "tool
  calling" as used elsewhere in this codebase (`chat_capability.py`,
  `tool_fallback.py`), which means a *model's* declared support for an
  OpenAI-style `tools` request parameter. Conflating the two terms was the
  exact ambiguity this ADR exists to resolve.
- **A2A Gateway** — contextual-orchestrator brokering Agent2Agent-protocol
  calls between internal agents. Not a synonym for MCP Gateway: MCP is
  agent-to-tool, A2A is agent-to-agent (Linux Foundation, n.d.).

### Aggregate / Entity / Value Object / Domain Service / Repository / Domain Event / Invariant

- **Value Object**: `WebSearchResult` — immutable (`frozen=True`), compared
  by value, no identity. Matches `PrivacyPolicyAssessment`'s existing shape
  in the sibling context.
- **Domain Service**: `web_search()` — stateless, no owned identity, operates
  across the Value Object. No class, no instance state, matching
  `crawl_policy_document`'s existing shape.
- **Aggregate / Entity / Repository**: deliberately **none** in this slice. A
  search has no persisted identity or lifecycle — it is a stateless
  read-through query, not a stored aggregate. Introducing a `SearchQuery`
  entity plus a repository now would be exactly the unrequested,
  speculative abstraction this repository's own Ponytail convention rejects
  (no aggregate for a value nothing yet needs to persist). The natural
  trigger to add one: a "grounding evidence" store that a future fact-check
  judge reads back, at which point the Aggregate's minimal transaction
  boundary should be one search call's result set, not individual rows.
- **Domain Event**: none emitted yet. Deferred trigger: once `web_search()`
  has a real caller needing an audit trail (cost/usage-ledger parity with LLM
  calls, or an OTel GenAI-style `web.search` span as the natural analogue of
  ADR 0122's `chat {model}` span convention for provider calls).
- **Invariants enforced at the boundary**: query non-empty and ≤
  `MAX_QUERY_LENGTH`; `max_results` bounded `1..MAX_RESULTS`; `engine ∈
  SUPPORTED_ENGINES`; the configured URL must be HTTPS or an explicit
  loopback HTTP address; the response body is bounded
  (`MAX_RESPONSE_BYTES`); a malformed *envelope* (not a dict, or missing the
  `results` list) fails closed, while individual malformed *rows* are
  dropped rather than propagated, because SearXNG itself federates multiple
  upstream engines and one upstream's bad row should not fail an otherwise
  usable query.

## Consequences

- Strix and Noema still cannot call `web_search()` today — no MCP server
  role, no A2A role, and no CLI/HTTP wiring ships in this change (see "What
  remains" below). This is deliberate: shipping a real, tested, 100%-covered
  library call is a sound first slice; wiring two unbuilt protocol gateways
  and an unready sandbox around it in the same change would not be
  verifiable end-to-end and would misrepresent readiness.
- Any operator who registers `SEARXNG_URL` (and optionally `SEARXNG_TOKEN`)
  can call `contextual_orchestrator.web_search.web_search()` today against
  their own SearXNG deployment — this is real, not a stub.
- The honesty gate on `web_search_options` in chat/completions is unaffected
  and must stay that way: this capability is a separate, explicitly-invoked
  function, never an implicit chat-completions parameter.
- Future MCP/A2A/Camoufox work has a recorded Bounded Context, Context Map,
  and Ubiquitous Language to build against, instead of re-deriving them (or
  silently conflating "tool calling" with "MCP Gateway," as the original
  request's phrasing risked) from scratch next iteration.
- The Wardnet-vs-`quarantine-sandbox-runtime` reconciliation for Camoufox
  isolation is now a recorded decision the product owner can override in a
  follow-up ADR, rather than a silent assumption in either direction.

## What remains (explicitly out of scope here)

1. Wire `web_search()` into an MCP server surface once a Strix or Noema
   caller is ready to consume it (Decision §2).
2. Design and build the A2A Gateway once a concrete two-agent delegation
   caller exists (Decision §3).
3. Build Camoufox browsing as a general capability, reusing the existing
   Wardnet+Camoufox-MCP boundary (Decision §4), and re-evaluate the
   `quarantine-sandbox-runtime` migration once
   `ContextualWisdomLab/.github#1590` is resolved and the runtime has a real
   `CommandExecutionBackend`-backed HTTP/CLI surface.
4. Add a second search engine (YaCy) once there is a real deployment to test
   the client against.
5. A Domain Event / span for `web_search()` calls, once a caller needs an
   audit trail.

## References

- Evans, E. (2003). *Domain-driven design: Tackling complexity in the heart
  of software*. Addison-Wesley.
- Fowler, M. (2014). *Bounded context*. martinfowler.com.
  https://martinfowler.com/bliki/BoundedContext.html
- Model Context Protocol. (n.d.). *What is the Model Context Protocol
  (MCP)?* Retrieved 2026-09-02, from https://modelcontextprotocol.io/
- Linux Foundation, Agent2Agent Project. (n.d.). *Agent2Agent (A2A)
  protocol*. Retrieved 2026-09-02, from https://a2a-protocol.org/latest/
- SearXNG Authors. (n.d.). *SearXNG search API*. Retrieved 2026-09-02, from
  https://docs.searxng.org/dev/search_api.html
- daijro. (n.d.). *Camoufox: Anti-detect browser built for web scraping &
  AI agents* [Software repository]. GitHub. Retrieved 2026-09-02, from
  https://github.com/daijro/camoufox
