# Tracks

| Track | Status | Purpose |
|---|---|---|
| 001-paper-grounded-orchestrator | active | Implement the source-backed orchestration contract with TDD, DDD, and CDD |
| 002-enterprise-design-foundation | active | Add paper-grounded screen design, user stories, REST API, code/DB conventions, and i18n |
| 003-chat-passthrough-honesty | active | Fail-closed OpenAI SDK fields before tools/response_format passthrough; seed/penalties/max_tokens/`n`/batch/`stop`/`user`/`logprobs`/`logit_bias`/`store`/`modalities`/`prediction`/`reasoning_effort`/`service_tier`/`metadata` hoisted. Serve tokens resolve from KV (`gateway_auth_token`). SSE-proxy + mode/trace owned by #617 — do not open a third SSE stack. Next: cherry-pick this tip onto #617; then KV provider-host allowlist |
