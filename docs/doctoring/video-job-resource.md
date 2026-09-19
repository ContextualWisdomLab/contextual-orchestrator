# Video job resource contract

The gateway treats video generation as an asynchronous resource. Submission
returns an opaque gateway identifier; later status and content requests resolve
the stored provider owner rather than selecting a model again. The provider job
identifier remains internal, and a provider lifecycle value is copied only as
observed data.

New registry entries keep immutable ownership in `video_job_records` and the
first complete token report in `video_job_usages`. Missing usage remains
unavailable, repeated polling cannot revise the first measured report, and
provider status is returned only as observed by the current provider response.
Standalone process-local storage makes no durability claim. Valkey is required
when restart or replica continuity matters.

The contract follows the HTTP asynchronous-resource model: the upstream video
API accepts work and exposes a polling resource, while HTTP semantics require
the gateway to describe acceptance without claiming completion. The gateway's
opaque id also prevents a provider-specific resource identifier from becoming
the public ownership key.

## Research grounding

Garcia-Molina and Salem's saga model treats long-lived work as a sequence of
durable local transactions with explicit recovery for partial execution. That
supports this gateway's ordering: persist the accepted provider job's ownership
first, then record optional observations. A later usage-store failure must not
erase or conceal the accepted resource, because retrying submission could create
additional remote work.

Birrell and Nelson's RPC design separates client-visible binding from a remote
implementation and analyzes call semantics under communication and machine
failure. That motivates the opaque gateway identifier and provider-affine owner
record: retries and follow-up calls bind to the already accepted remote job
without exposing or reselecting the provider resource identity.

The two papers are ACM publications. Redistribution permission for their PDFs
has not been established, so this PR does not vendor copies; it supplies full
citations, DOI links, and the design summaries above as permitted by the
repository research-grounding rule.

## References

Birrell, A. D., & Nelson, B. J. (1984). Implementing remote procedure calls.
*ACM Transactions on Computer Systems, 2*(1), 39–59.
https://doi.org/10.1145/2080.357392

Garcia-Molina, H., & Salem, K. (1987). Sagas. In *Proceedings of the 1987 ACM
SIGMOD International Conference on Management of Data* (pp. 249–259).
https://doi.org/10.1145/38713.38742

OpenRouter. (2026). *Video generation*. OpenRouter documentation.
https://openrouter.ai/docs/guides/overview/multimodal/video-generation

Fielding, R. T., Nottingham, M., & Reschke, J. (2022). *HTTP semantics* (RFC
9110). Internet Engineering Task Force. https://www.rfc-editor.org/rfc/rfc9110
