- Review-sidecar `orchestrator/free` admission now includes a CI-seeded
  `OPENCODE_ZEN_API_KEY` as an authorized free-pool source. Honest-free
  OpenCode Zen and OpenCode Go rows enter `G ∩ P ∩ R`; `OPENAI_API_KEY`
  remains globally discoverable and is still excluded from the review pool.
- The hourly workflow contract now verifies that `OPENCODE_ZEN_API_KEY` reaches
  the same bootstrap boundary instead of silently omitting its regression check.
- Tool calls now reject deferred batch routing, generated planners no longer
  inherit worker tools, and structured group failover records each failed
  member before a later candidate succeeds.
