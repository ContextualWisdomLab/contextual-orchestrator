# Model auto-discovery

This gateway is the ContextualWisdomLab model-performance router. Downstream
apps (gyeot, scopeweave, naruon, and siblings) call one OpenAI-compatible
`/v1` and receive a **discovered** worker pool — not a hard-coded two-model
catalog.

## Floor, not inventory

These NVIDIA NIM ids are used **only** when every registered catalog fetch
returns nothing (empty, malformed, 4xx/5xx, or timeout):

| Size class | Model id |
|---|---|
| default (quality / Fugu-Ultra conduct) | `nvidia-nim/nvidia/nemotron-3-ultra-550b-a55b` |
| small (latency / Fugu route) | `nvidia-nim/nvidia/nemotron-3-super-120b-a12b` |

A successful `GET /v1/models` (or Bytez native list) **replaces** that floor.

## Credential names (KV only)

Discovery looks up these names with `get_credential`. A miss is `None`. The
product does **not** treat `os.getenv` as “the key is registered.”

- `NVIDIA_NIM_API_KEY`
- `NVIDIA_NIM_API_KEY_SUB`
- `BYTEZ_API_KEY`
- `OPENROUTER_API_KEY`
- `OPENAI_API_KEY`

Bootstrap still may pipe an Actions secret into `register-credential`. That is
transport into the KV, not the runtime source.

## Price honesty

- Explicit billed `0` is known-free.
- A free channel that still has a published list price or a paid `:free`
  sibling stores `original_list_price` and is **compared at that list price**.
- Missing, boolean, non-numeric, negative, NaN, or infinite prices are
  `unknown`. Unknown is never converted to `0` / “free.”

## Fugu / Conductor / TRINITY allocation

Discovered chat models receive role tags:

- **Fugu route** — one worker; capability first, then known cost.
- **Conductor conduct** — natural-language steps with access lists.
- **TRINITY** — thinker / worker / verifier (plus synthesizer) on those tags.

Large / ultra ids are tagged for planning, writing, and review. Small / super
ids are tagged cheap / fallback / coding so latency routing has a worker.

## Surfaces

| Method | Path | Who |
|---|---|---|
| `GET` | `/v1/models` | inference — `contextual-orchestrator` plus current pool ids |
| `GET` | `/api/v1/provider_catalogs` | admin — last secret-redacted snapshot |
| `POST` | `/api/v1/provider_catalogs/refresh` | admin — re-run discovery |

Startup (`python -m contextual_orchestrator --serve`) applies discovery when
any of the five names is already in the KV. No registered key keeps the seed
/ mock pool so local tests stay offline.

## Research grounding

Routing and catalog composition are grounded in the papers already vendored
under `docs/papers/` (FrugalGPT, RouteLLM, Hybrid LLM) plus the Fugu /
Conductor / TRINITY sources cited in `docs/architecture.md`. This document is
operator/product contract, not an ADR — architecture decision records are
owned by the researcher docs PR.
