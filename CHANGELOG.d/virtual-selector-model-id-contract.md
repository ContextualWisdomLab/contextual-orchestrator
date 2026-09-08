- Pinned the virtual-selector model-id contract: `orchestrator/free` and
  `orchestrator/auto` (with or without surrounding whitespace) route, while
  provider-prefixed or differently cased forms such as
  `openai/orchestrator/free`, `openai/orchestrator/auto`,
  `openai/contextual-orchestrator`, `ORCHESTRATOR/FREE`, and
  `ORCHESTRATOR/AUTO` are refused with `400 invalid_model`. The tools gate
  matches these ids exactly, so normalizing provider prefixes or case would
  widen it silently and send requests the caller never routed into single-agent
  passthrough, losing worker re-selection.
