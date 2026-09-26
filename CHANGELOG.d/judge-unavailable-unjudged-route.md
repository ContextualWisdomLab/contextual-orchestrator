# Mark unavailable-judge verdicts instead of penalising route candidates

Policy change proposal (needs reviewer sign-off against ADR 0001).

- `_model_judge_verification` still rejects when no verdict can be produced
  (fast-mlsirm missing or broken, or the judge call itself fails), as ADR 0001
  requires, but now marks those results `judge_status: "unavailable"` so they
  are distinguishable from a judged rejection.
- `route_once` no longer records a quality-ledger or psychometric failure for a
  candidate whose answer was never judged, and stops the judge cascade instead
  of spending another provider call on a lower-ranked candidate that would meet
  the same missing judge. It returns the top-ranked answer, still with
  `accepted: false`, and carries the marker on the verification and trace row.
- `conduct` behaviour is unchanged (an unavailable judge still selects the
  worker output); only the marker is added to its verification.
