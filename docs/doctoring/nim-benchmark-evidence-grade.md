# Evidence-grade NVIDIA NIM benchmark: engineering decision record

## Decision

The NVIDIA NIM benchmark is an optional, provider-neutral evaluation adapter.
It is not imported by the normal package initializer and it never modifies the
runtime gateway as an import side effect. Live execution uses the same
validation-time-address-pinned HTTPS boundary as the gateway, while dry
execution remains deterministic, network-free, and credential-free.

The benchmark is evidence-generating rather than policy-authorizing. It records
what was discovered, attempted, completed, skipped, measured, estimated, and
unknown. It never changes production routing automatically. A report below the
explicit evidence floor is labeled `insufficient_evidence`, and every report
keeps `routing_recommendation` null so a responsible human review remains
necessary.

## Architecture and MSA boundary

`contextual_orchestrator/nim_benchmark.py` owns catalog discovery, capability
probing, equal-budget policy comparison, evidence validity, uncertainty,
Pareto analysis, and artifact serialization. The ordinary gateway remains
standalone and provider-neutral. Other ContextualWisdomLab services may invoke
the benchmark as a module or CLI without taking ownership of its transport,
credential, pricing, or evidence rules.

The boundary preserves the following responsibilities:

- the host workflow owns GitHub Secret delivery and immutable run provenance;
- the benchmark moves the secret into the process-local credential registry and
  resolves it by the `NVIDIA_NIM_API_KEY` credential name;
- the benchmark owns bounded provider calls and secret-redacted artifacts;
- the central `.github` repository owns independent review and protected-branch
  policy; and
- consumers such as naruon may read artifacts but do not receive authority to
  reinterpret unknown prices or incomplete evidence as production facts.

## Provider-egress security contract

A conventional URL opener is not used for live NIM requests. Validation and
connection are one security boundary:

1. Parse an HTTPS URL and reject missing hostnames.
2. Resolve the hostname once for that request.
3. Reject any answer that is not globally routable, including private,
   loopback, link-local, multicast, reserved, unspecified, IPv6 unique-local,
   and RFC 6598 shared address space.
4. Dial only an address from that exact validation result.
5. Preserve the original hostname for HTTP authority, TLS SNI, and certificate
   hostname verification.
6. Do not consult environment proxy settings.
7. Reject every redirect before a bearer credential can reach another origin.
8. Close responses and connections deterministically and use only another
   address from the same validation result for fallback.
9. Read at most 8 MiB plus one sentinel byte from a provider response and fail
   closed before an oversized body can be materialized into benchmark evidence.

RFC 6598 defines `100.64.0.0/10` as shared, non-globally-routable address space.
RFC 4193 defines IPv6 unique-local addresses as local rather than globally
routable. RFC 9110 defines redirects as new target-URI actions and identifies
`Authorization` as resource-specific credential material that merits removal
when redirecting. The implementation chooses the narrower fail-closed policy of
not following redirects at all.

## Dynamic discovery and deterministic probe allocation

`GET /v1/models` is the run-time source of the model inventory. Model identifiers
are not hard-coded as authoritative catalog entries. The parser records invalid
and duplicate entries and sorts the usable inventory.

Every discovered model receives a row for every supported probe contract. Before
threads start, the benchmark constructs the complete ordered
`(model_id, capability_name)` plan and allocates the remaining request budget in
that stable order. Only allocated cells execute concurrently. Non-allocated
cells receive the same machine-readable budget reason on every run. Thread
scheduling therefore cannot decide which evidence exists.

The video-understanding probe contains a deterministic, decodable one-frame H.264
MP4. Its embedded bytes have SHA-256
`777dda43b5a15162b68a39aa486d5c70c9994d7fe761742fd00d4e13508983c0`.
Startup validation confirms the ISO Base Media File Format structure, a video
handler, AVC sample entry, 16 × 16 dimensions, one sample, and media data. This
prevents a malformed `ftyp`-only stub from turning a capable video model's valid
rejection into a false unsupported classification.

## Fair policy comparison

Direct single-worker, `route_once`, bounded `conduct`, and reviewed
cheapest-worker cells receive the same per-task contract:

- one locked task and scorer version;
- one total prompt-plus-completion token allowance;
- one five-call maximum envelope;
- one timeout policy; and
- one workflow-depth ceiling.

The token allowance is cell-wide rather than per request. Prompt estimates are
charged before a call, the output cap is reduced to the remaining allowance,
and provider-reported usage replaces the latest estimate when valid. Booleans,
negative values, NaN, and infinities are not accepted as token counts. A deep
policy cannot obtain five times a single-call arm's total token budget merely by
issuing five calls.

## Cost evidence and price honesty

Actual access cost and hypothetical production cost are separate fields and
separate evidence classes.

As reviewed on 2026-08-05, NVIDIA's NIM General FAQ states that NVIDIA Developer
Program members have free access to hosted NIM API endpoints for prototyping.
The same source distinguishes development, testing, research, and evaluation
from production and states that production requires NVIDIA AI Enterprise. The
report therefore records `actual_cost_usd = 0.0` only for the reviewed hosted
endpoint access context, includes the exact source, review date, validity
horizon, program scope, production distinction, and uncertainty, and refuses a
live run after 2026-09-04 until the source is reviewed again.

No NVIDIA model price is embedded or inferred. A live hypothetical pricing
scenario is optional; absence means `unknown`. If supplied, it must be marked
`reviewed` and include an HTTPS source, reviewer, review date, validity horizon,
rate basis, uncertainty, and explicit input/output rates. Unreviewed, future,
incomplete, or expired evidence fails before network egress. The included
example remains deliberately `example_unreviewed` and is valid only for dry-run
schema testing.

NVIDIA's offering documentation further distinguishes exploratory/free NIM
availability from NIM Certified, which requires NVIDIA AI Enterprise for
enterprise lifecycle, CVE, support, and compliance expectations. The benchmark
does not convert free prototype access into a claim about production licensing,
support, or per-model production price.

## Evidence sufficiency and uncertainty

The bundled ten-task manifest is a smoke test. It verifies the integration
surface but cannot authorize production routing. The governance floor is:

- at least 30 locked paired tasks shared by compared policies; and
- at least 90% successful cells across the requested comparison matrix.

These values are explicit conservative release-governance thresholds, not a
claim of universal statistical sufficiency. The artifact reports the observed
paired-task count, requested thresholds, completion fraction, and whether the
run is `insufficient_evidence` or `evidence_review_required`. Even when the floor
is met, production routing remains a human decision and
`routing_recommendation` stays null.

Paired bootstrap intervals preserve task pairing and expose uncertainty in mean
score differences. Pareto frontiers show quality against latency and reviewed
hypothetical cost; policies with unknown cost are excluded from that cost
frontier and named explicitly. HELM motivates standardized multi-metric
conditions and visible incompleteness. FrugalGPT and RouteLLM motivate measuring
cost-quality routing trade-offs, but their results are not treated as evidence
for this repository's models or tasks.

## Workflow and credential separation

`.github/workflows/nim-benchmark.yml` has separate dry and live jobs. The dry job
never receives `NVIDIA_NIM_API_KEY`. Only the live benchmark step receives the
GitHub Secret, and the credential is never passed through argv or written to an
artifact. Both jobs use immutable action revisions, bounded execution, and
single-flight concurrency. The workflow cannot merge, release, approve its own
changes, or modify routing configuration.

The ordinary test workflow separately proves:

- complete focused production statement and branch coverage;
- 100% public docstrings;
- wheel build and clean-environment import;
- no eager optional benchmark import;
- no compatibility monkeypatch module;
- no temporary branch-writing or source-export repair job; and
- no retained one-use transformation payload.

## Verification contract

An exact pull-request head is eligible for review only after all of the following
succeed:

- deterministic unit and adversarial security tests;
- transport tests for DNS rebinding, proxy isolation, redirects, SNI/authority,
  address fallback, bounded response bodies, and cleanup;
- deterministic probe-allocation and valid media-fixture tests;
- live pricing and access-evidence expiry tests that prove failure before egress;
- equal token/call budget tests for every comparison arm;
- evidence-sufficiency, Pareto, provenance, and secret-redaction tests;
- 100% statement and branch coverage for the production benchmark module;
- 100% public docstrings;
- package build, install, and import smoke tests;
- repository Tests, Fuzz, Security, Security Scan, and SAST; and
- independent exact-head review with no unresolved actionable thread.

No earlier head, local-only result, queued check, or stale approval is accepted as
release evidence.

## References

Autio, C., Schwartz, R., Dunietz, J., Jain, S., Stanley, M., Tabassi, E., Hall,
P., & Roberts, K. (2024). *Artificial intelligence risk management framework:
Generative artificial intelligence profile* (NIST AI 600-1). National Institute
of Standards and Technology. https://doi.org/10.6028/NIST.AI.600-1

Chen, L., Zaharia, M., & Zou, J. (2023). FrugalGPT: How to use large language
models while reducing cost and improving performance. *arXiv*.
https://doi.org/10.48550/arXiv.2305.05176

Fielding, R., Nottingham, M., & Reschke, J. (2022). *HTTP semantics* (RFC 9110;
STD 97). RFC Editor. https://doi.org/10.17487/RFC9110

Hinden, R., & Haberman, B. (2005). *Unique local IPv6 unicast addresses*
(RFC 4193). RFC Editor. https://doi.org/10.17487/RFC4193

Liang, P., Bommasani, R., Lee, T., Tsipras, D., Soylu, D., Yasunaga, M., Zhang,
Y., Narayanan, D., Wu, Y., Kumar, A., Newman, B., Yuan, B., Yan, B., Zhang, C.,
Cosgrove, C., Manning, C. D., Ré, C., Acosta-Navas, D., Hudson, D. A., … Koreeda,
Y. (2023). Holistic evaluation of language models. *Transactions on Machine
Learning Research*. https://doi.org/10.48550/arXiv.2211.09110

NVIDIA Corporation. (n.d.). *General FAQ*. NVIDIA NIM Documentation. Retrieved
August 5, 2026, from https://docs.api.nvidia.com/nim/docs/product

NVIDIA Corporation. (2026, June 4). *NIM offerings*. NVIDIA NIM for Large
Language Models. https://docs.nvidia.com/nim/large-language-models/2.0.5/about-nim-llm/nim-offerings.html

Ong, I., Almahairi, A., Wu, V., Chiang, W.-L., Wu, T., Gonzalez, J. E., Kadous,
M. W., & Stoica, I. (2024). RouteLLM: Learning to route LLMs with preference
data. *arXiv*. https://doi.org/10.48550/arXiv.2406.18665

Weil, J., Kuarsingh, V., Donley, C., Liljenstolpe, C., & Azinger, M. (2012).
*IANA-reserved IPv4 prefix for shared address space* (RFC 6598; BCP 153). RFC
Editor. https://doi.org/10.17487/RFC6598
