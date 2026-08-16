# Papers grounding the cost-review + routing hub

These papers ground the design of the LLM **cost review** ledger and the
**sync-vs-batch / upstream** routing added in `feat/cost-review-and-batch-routing`.
All three are arXiv preprints distributed under licenses that permit
redistribution; each is cited below with its arXiv identifier.

## Cost optimisation

- **FrugalGPT: How to Use Large Language Models While Reducing Cost and
  Improving Performance** — Lingjiao Chen, Matei Zaharia, James Zou. arXiv:2305.05176, 2023.
  `frugalgpt-cost-2305.05176.pdf`
  Motivates the **configurable price table + per-request cost accounting** and
  cost-optimising model selection: cost varies by orders of magnitude across
  providers/models, so a gateway should price each request and route to the
  cheapest capable upstream. Distributed under arXiv's non-exclusive license to
  distribute (arXiv perpetual, non-exclusive license 1.0).

## Query routing (which upstream / which tier)

- **RouteLLM: Learning to Route LLMs with Preference Data** — Isaac Ong, Amjad
  Almahairi, Vincent Wu, Wei-Lin Chiang, Tianhao Wu, Joseph E. Gonzalez, M.
  Waleed Kadous, Ion Stoica. arXiv:2406.18665, 2024.
  `routellm-routing-2406.18665.pdf`
  Grounds the **routing decision** layer (`RoutingPolicy` + cost-aware upstream
  selection): route strong/weak model choices to hit a cost/quality target.
  arXiv preprint; distributed under the arXiv non-exclusive distribution license.

- **Hybrid LLM: Cost-Efficient and Quality-Aware Query Routing** — Dujian Ding,
  Ankur Mallick, Chi Wang, Robert Sim, Subhabrata Mukherjee, Victor Rühle,
  Laks V. S. Lakshmanan, Ahmed Hassan Awadallah. arXiv:2404.14618 (ICLR 2024).
  `hybrid-llm-query-routing-2404.14618.pdf`
  Grounds **latency-tolerant vs interactive routing** and the sync/batch split:
  route easy/bulk queries to the cheaper path, keep hard/interactive queries on
  the responsive path. Distributed under the arXiv non-exclusive license /
  CC BY as marked on arXiv.

## API contract honesty (tool schema omit)

Gateway buyers send official OpenAI SDK payloads. Optional
`tools[].function.description`, `parameters`, and `strict` are often serialized
as JSON `null` rather than omitted. Those nulls must be popped before the
provider hop; accepting them in place is not omit-equivalent and several
OpenAI-compatible backends reject a null JSON Schema object.

- OpenAI. (2024). *Create chat completion*. OpenAI API reference.
  https://platform.openai.com/docs/api-reference/chat/create
  Grounds the optional function-tool fields and the omit-vs-present contract
  the gateway must preserve on passthrough.
- Bray, T. (Ed.). (2017). *The JavaScript Object Notation (JSON) data
  interchange format* (RFC 8259). Internet Engineering Task Force.
  https://doi.org/10.17487/RFC8259
  Distinguishes a present `null` member from an omitted member. Redistribution
  of the RFC text is not required here; the citation is the normative source.

## Batch execution / load balancing

The external `pg-llm-batch` service carries its own grounding papers, including
PagedAttention / vLLM (2309.06180) and DeepSpeed-FastGen (2401.08671), which
motivate throughput-oriented **batched** inference and the load-balancing that
makes the latency-tolerant batch route economical. Those sources are referenced
but not vendored here so this repository remains one deployable control plane.

## Trusted-trace personal data (no irreversible email mask)

Operational PII on a trusted caller trace is an access-control problem, not a
masking problem. Destroying the email on an invoice or HR ticket paralyzes
the operator. NIST SP 800-122 is a US government publication (cite + link);
ISO/IEC 27001 is cited, not attached.

- McCallister, E., Grance, T., & Scarfone, K. (2010). *Guide to protecting
  the confidentiality of personally identifiable information (PII)* (NIST
  Special Publication 800-122). National Institute of Standards and
  Technology. https://doi.org/10.6028/NIST.SP.800-122
  Confidentiality of PII is achieved by limiting who can see the identifier
  and logging that access — not by irreversibly destroying it on the
  operational work surface. Buyer next action: set
  `include_orchestration_trace` only for trusted callers.

- Joint Task Force. (2020). *Security and privacy controls for information
  systems and organizations* (NIST Special Publication 800-53 Rev. 5).
  National Institute of Standards and Technology.
  https://doi.org/10.6028/NIST.SP.800-53r5
  Controls **AC-3** (Access Enforcement) and **AU-2** (Event Logging) are
  the substitute for email `[REDACTED]` on trusted traces. Credential
  material remains redacted.

## Authenticator management (gateway Bearer tokens)

NIST SP 800-53 and SP 800-63B are US government publications; this repo
cites them rather than vendoring the full PDFs.

- Joint Task Force. (2020). *Security and privacy controls for information
  systems and organizations* (NIST Special Publication 800-53 Rev. 5).
  National Institute of Standards and Technology.
  https://doi.org/10.6028/NIST.SP.800-53r5
  Control **IA-5** (Authenticator Management) is the request-time source
  for serve Bearer tokens: `gateway_auth_token`, `admin_auth_token`, and
  `inference_auth_token` live in the credential KV. Seed and resolve
  strip surrounding whitespace. Buyer next action: pass `--auth-token`
  or start once with `CONTEXTUAL_ORCHESTRATOR_TOKEN`. Rotate a persisted
  key with `--auth-token` or `register-credential`.

- Grassi, P. A., Garcia, M. E., & Fenton, J. L. (2017). *Digital identity
  guidelines: Authentication and lifecycle management* (NIST Special
  Publication 800-63B). National Institute of Standards and Technology.
  https://doi.org/10.6028/NIST.SP.800-63b
  Authenticators are secrets resolved from a registry, not ambient
  process environment. A later env edit must not change a live process
  or a persisted key.
  The guideline text is not attached (US government work is cited, not
  redistributed here).

## Boundary protection (provider host allowlist)

ISO/IEC 27001 cannot be redistributed here. NIST SP 800-53 is a US government
publication; this repo cites it rather than vendoring the full PDF.

- Joint Task Force. (2020). *Security and privacy controls for information
  systems and organizations* (NIST Special Publication 800-53 Rev. 5).
  National Institute of Standards and Technology.
  https://doi.org/10.6028/NIST.SP.800-53r5
  Control **SC-7** (Boundary Protection) is the request-time hostname
  allowlist: only approved provider hosts may receive a credentialed egress
  call. Buyer next action: seed `provider_egress.allowed_provider_hosts`.

- International Organization for Standardization. (2022). *Information
  security, cybersecurity and privacy protection — Information security
  controls* (ISO/IEC 27001:2022). https://www.iso.org/standard/27001
  Annex **A.8.20** (Network security) is the same allowlist expressed as an
  operator control. The standard text is not attached (copyright).

> Citations are provided for scholarly attribution. Redistribution here relies
> on the arXiv non-exclusive distribution license each author granted; no
> GPL/AGPL-licensed material is vendored anywhere in this repository.
