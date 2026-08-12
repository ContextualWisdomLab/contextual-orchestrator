# Role-differentiated reasoning effort

## Citation (APA 7th)

Snell, C., Lee, J., Xu, K., & Kumar, A. (2024). Scaling LLM test-time compute
optimally can be more effective than scaling model parameters
(arXiv:2408.03314). https://doi.org/10.48550/arXiv.2408.03314

## Relevance

`OrchestrationPolicy.role_temperature` differentiates sampling temperature by
paper role (thinker / worker / verifier / synthesizer) so operators can ablate
test-time compute allocation without collapsing multi-agent depth. Lower
verifier temperature prioritizes stability; worker defaults remain higher for
exploration.
