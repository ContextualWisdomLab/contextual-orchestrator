# Tracks

| Track | Status | Purpose |
|---|---|---|
| 001-paper-grounded-orchestrator | active | Implement the source-backed orchestration contract with TDD, DDD, and CDD |
| 002-enterprise-design-foundation | active | Add paper-grounded screen design, user stories, REST API, code/DB conventions, and i18n |
| 003-chat-passthrough-honesty | active | Fail-closed OpenAI SDK fields before tools/response_format passthrough; seed/penalties/max_tokens/`n`/batch/`stop`/`user`/`logprobs`/`logit_bias` hoisted. Omit-equivalent `max_completion_tokens` no longer masks sibling `max_tokens=0`. Next: cherry-pick `store`/`modalities`/`prediction`/`reasoning_effort`/`service_tier`/`metadata` from #609 onto the SSE tip (#606), not another stack merge |
