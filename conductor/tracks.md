# Tracks

| Track | Status | Purpose |
|---|---|---|
| 001-paper-grounded-orchestrator | active | Implement the source-backed orchestration contract with TDD, DDD, and CDD |
| 002-enterprise-design-foundation | active | Add paper-grounded screen design, user stories, REST API, code/DB conventions, and i18n |
| 003-sdk-omit-real-persist | active | #668 re-land accepted SDK omit 200s without write-back. Persist args/instructions/metadata and hoist chat top_logprobs before tools passthrough. Prefer the persist successor over merging the 145-file #668 stack. |
| 003-compatibility-honesty | active | Fail-closed ASCII `[a-zA-Z0-9_-]{1,64}` on `json_schema.name` and `tool.function.name` (`str.isalnum()` leaked Unicode). Re-landed on #686 substrate after parallel tip #685. Do not merge 140-file honesty stacks onto `main`. |
