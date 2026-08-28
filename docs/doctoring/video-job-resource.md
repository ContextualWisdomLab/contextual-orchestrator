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

## References

OpenRouter. (2026). *Submit a video generation request*. OpenRouter API
Reference. https://openrouter.ai/docs/api/api-reference/video-generation/create-videos

OpenRouter. (2026). *Video generation*. OpenRouter documentation.
https://openrouter.ai/docs/guides/overview/multimodal/video-generation

Fielding, R. T., Nottingham, M., & Reschke, J. (2022). *HTTP semantics* (RFC
9110). Internet Engineering Task Force. https://www.rfc-editor.org/rfc/rfc9110
