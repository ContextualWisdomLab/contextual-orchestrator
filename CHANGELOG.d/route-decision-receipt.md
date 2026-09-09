# Route decision receipt boundary contract

- Add additive `request_route_decision_receipt` returning
  `route_decision_receipt` fields on one `time.monotonic` clock, excluding
  slow generation via post-probe `admitted_first_at`.
- Return `unavailable` on failed probe, never fabricated `success`; let
  cancellation propagate.
- Stub-grade GREEN for #1110 boundary tests only; no durable journal, workload
  command, or p95 numbers yet.
