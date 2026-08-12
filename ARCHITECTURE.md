# Architecture

Canonical product architecture for `contextual-orchestrator` lives in
[`docs/architecture.md`](docs/architecture.md).

## Role

Org LLM gateway: OpenAI-compatible front door with cost-aware routing, sync vs
batch policy, multi-agent conduct path (thinker → worker → verifier →
synthesizer), KV-backed credentials, and commercial evidence surfaces.

## Control flow

```text
Client → server.py (auth / validate)
       → TaskOrchestrator.complete
            ├─ route  (single worker; optional price_per_million tie-break)
            └─ conduct (workflow steps + access lists)
       → ModelClient (mock:// or HTTPS; retries; failover; circuit breaker)
       → OpenAI-shaped completion / SSE
```

## Security & compliance notes

- Runtime secrets: `get_credential` (KV), not request-time `os.getenv`.
- Provider egress: block loopback/private/reserved; TLS verify by default.
- Release authorization evidence is fail-closed on exact protected-head checks
  (see `docs/commercial_release_candidate.md`).
- Vulnerability disclosure: `SECURITY.md` and
  `docs/doctoring/security-disclosure-lifecycle.md` (ISO/IEC 29147 / 30111;
  NIST SSDF).

## Research grounding

Paper-backed routing claims (Fugu, TRINITY, Conductor) are contracted in
`tests/test_paper_contracts.py` and summarized in `docs/architecture.md` with
APA 7th citations under `docs/papers/` when redistribution permits.
