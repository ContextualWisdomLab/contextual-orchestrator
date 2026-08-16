# Tracks

| Track | Status | Purpose |
|---|---|---|
| 001-paper-grounded-orchestrator | active | Implement the source-backed orchestration contract with TDD, DDD, and CDD |
| 002-enterprise-design-foundation | active | Add paper-grounded screen design, user stories, REST API, code/DB conventions, and i18n |
| 003-chat-passthrough-honesty | active | Fail-closed OpenAI SDK fields before tools/response_format passthrough on the #624 SSE tip. Omit-equivalent `max_completion_tokens` no longer masks sibling `max_tokens=0`; JSON `top_logprobs: false` is `invalid_top_logprobs`. Do not merge #625/#605/#606/#609 stacks. Next: remaining `__main__.py` bind/TLS/sqlite flags on #621 after #624 lands |
