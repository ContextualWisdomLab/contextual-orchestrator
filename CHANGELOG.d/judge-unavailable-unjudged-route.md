# Split judge failures into misconfigured, unavailable, and ordinary rejections

Every judge failure still rejects (ADR 0001: `accepted` stays `false`). The
verdict is now also classified by what the failure says about the answer:

- `judge_status: "misconfigured"`: fast-mlsirm is missing, broken, or cannot
  be constructed, or there is no eligible judge agent (previously a
  `StopIteration` that fell into the catch-all). Logged at error level.
- `judge_status: "unavailable"`: the judge's own provider call hit a transient
  failure (timeout, `OSError`, upstream 5xx or rate limit,
  `EndpointUnavailableError`, `BudgetExceededError`). The gateway's judge
  adapter records the exception at the provider-call boundary, because
  fast-mlsirm re-raises adapter failures as `JudgeFormatError` without a
  cause. Logged at warning level.
- No marker: everything else, including failures the candidate answer can
  cause (request too large, missing assistant content, exhausted structured
  output, parse or encoding errors) and unknown exceptions. These stay ordinary
  rejections exactly as before.

For unjudged verdicts (either marker), `route_once` records no quality-ledger
or psychometric observation, stops failing over, and returns the top-ranked
answer with the marker on its verification and trace row. Streamed and batched
answers get the same marker on the persisted verification and trace, and also
record no observation. Unjudged results are not written to the response cache.
`conduct` keeps the ADR 0001 worker fallback and carries the marker. ADR 0034's
real-time judging section describes the split.
