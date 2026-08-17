# Changelog

## Unreleased

### Unique slice (not PR #642)

PR #642 (`cursor/provider-catalog-seed-546c`) owns the production seed,
flag-gated `--discover-models`, OpenCode sidecar, and 429 → next-agent
failover. This release does **not** duplicate that work.

- **Default discovery.** When an org KV credential is present, compose
  chat models from `GET {base_url}/models`. Static fallback only if that
  GET fails. Exception-isolated per provider. No `--discover-models` flag.
  Discovery reuses chat egress: reject loopback/private/reserved
  destinations before attaching a KV Bearer, then GET through
  `ModelClient` (no second urllib client).
- **`original_list_price`.** Hypothetical/published list, stored beside
  billed rates. Explicit billed `0` is actual free-to-caller. A missing
  price row is `unknown` (`None`) — never converted to `0` / “free”
  (issue #86 honesty bug in `PriceBook.compute_cost`).
- **Min-cost / max-performance selection.** One worker per step
  (Fugu / FrugalGPT / Hybrid LLM / Trinity). Transient retry on the chosen
  worker; no sequential next-agent hop. Circuit-open agents are skipped on
  the next selection.
- **`GET /v1/models`.** OpenAI-shaped composed catalog for first-class
  `/v1` consumers, including **Noema** (review and other jobs).
- GitHub Models hosts and `COPILOT_GITHUB_TOKEN` are rejected.

See `docs/doctoring/priced-selection.md` (APA 7th citations).
