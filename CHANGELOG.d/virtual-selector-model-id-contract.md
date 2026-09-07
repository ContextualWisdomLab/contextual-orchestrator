- Pinned the virtual-selector model-id contract: `orchestrator/free` (with or
  without surrounding whitespace) routes, while `openai/orchestrator/free`,
  `openai/contextual-orchestrator`, and `ORCHESTRATOR/FREE` are refused with
  `400 invalid_model`. The tools gate matches these ids exactly, so normalizing
  provider prefixes or case would widen it silently and send requests the caller
  never routed into single-agent passthrough, losing worker re-selection.
