- Virtual `orchestrator/free` structured completions (`response_format`, no
  tools/stream) fail over a retryable synthesizer 502/429 onto the next
  eligible free worker and attach request-scoped eligible/attempted
  receipts. Concrete model pins stay sticky. Default model timeout remains
  null (issue #1045; Inkspan Noema job 101628090366 on base `414f2297`).
