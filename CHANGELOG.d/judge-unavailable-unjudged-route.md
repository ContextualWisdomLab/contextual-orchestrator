# Split judge failures into misconfigured, unavailable, and ordinary rejections

Every judge failure still rejects (ADR 0001: `accepted` stays `false`). The
verdict is now also classified by what the failure says about the answer:

- `judge_status: "misconfigured"`: fast-mlsirm is missing, broken, or cannot
  be constructed, or there is no eligible judge agent (previously a
  `StopIteration` that fell into the catch-all). Logged at error level, at
  most once per distinct reason per 300 seconds per process (debug level in
  between), so a broken judge does not log an error on every request.
- `judge_status: "unavailable"`: the judge's own provider call failed for a
  reason that says nothing about the answer: anything the canonical provider
  taxonomy marks retryable, any judge 5xx (including 501, 505, 507, and
  Cloudflare 520-530, which the taxonomy marks non-retryable or leaves
  unmapped), connection, DNS (including NXDOMAIN) and TLS failures (including
  certificate verification), timeouts and other `OSError`s,
  `EndpointUnavailableError`, and `BudgetExceededError`. The reason reads
  "model judge call failed transiently", not "invalid structured verdict". The
  gateway's judge adapter records the exception at the provider-call
  boundary, because fast-mlsirm re-raises adapter failures as
  `JudgeFormatError` without a cause. An HTTP status is checked before the
  `OSError` fallback, so a raw `HTTPError` 400 or 413 is never `unavailable`.
  Logged at warning level.
- No marker: everything else, including failures the candidate answer can
  cause (request too large, missing assistant content, exhausted structured
  output, parse or encoding errors), any other 4xx, and unknown exceptions.
  These stay ordinary rejections exactly as before.

For unjudged verdicts (either marker), `route_once` records no quality-ledger
or psychometric observation, stops failing over, and returns the answer of the
attempt whose judging could not run, with the marker on its verification and
trace row. That is the top-ranked candidate unless earlier candidates were
already judged and rejected. Streamed and batched answers get the same marker
on the persisted verification and trace, and also record no observation.
Unjudged results are not written to the response cache. `conduct` keeps the
ADR 0001 worker fallback and carries the marker. ADR 0034's real-time judging
section describes the split.
