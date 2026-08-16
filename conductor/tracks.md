# Tracks

| Track | Status | Purpose |
|---|---|---|
| 001-paper-grounded-orchestrator | active | Implement the source-backed orchestration contract with TDD, DDD, and CDD |
| 002-enterprise-design-foundation | active | Add paper-grounded screen design, user stories, REST API, code/DB conventions, and i18n |
| 003-chat-passthrough-honesty | active | Fail-closed OpenAI SDK fields before tools/response_format passthrough. This tip: SSE tools proxy, mock `delta.tool_calls`, streamed nucleus/penalties, KV provider-host allowlist, and process-bootstrap sqlite/Clearfolio/CA paths (seed-once, CLI wins). Next: persist `provider_egress` and `process_bootstrap` on the credential KV backend. Do not fold #621 token KV into this slice. |
