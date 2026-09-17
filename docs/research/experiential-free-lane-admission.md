# Experiential free-lane admission

Experiential's public model listing does not establish that a model is
free-only. Its model waterfall can move from a free tier to credit-funded
provider deployments after the free limit, subject to an organization setting.
The public API contract documents no request field or header that forces a
free-only route. The authenticated UI's `FREE` label therefore cannot be used
as pricing or privacy evidence for a serving request.

The general free selector keeps ordinary Experiential discovery available for
paid routing, but excludes all Experiential rows until an enforceable,
deployment-specific free-only contract is available. This is deliberately
separate from ZDR: the UI's data column and the provider's retention evidence
do not prove free-only execution.

References:

- https://platform.experientiallabs.ai/llms.txt
- https://platform.experientiallabs.ai/docs/models
