- Virtual `route_once`/`conduct` routes advance to the next eligible
  candidate after an explicit provider HTTP 503 instead of replaying the
  same candidate first, so a pool where every route returns 429/503 is
  attempted once per candidate before the last classified error is returned.
  The only or last candidate keeps the bounded same-candidate retry (a lone
  candidate that returns one 503 and then succeeds is still served); a
  provider-stated 503 `Retry-After` of up to 30 s is the floor for that
  retry's delay, and a longer one skips the inline retry. A 503 still counts
  toward the provider health circuit; 502/504, the non-standard 529
  ("overloaded", not treated as an explicit rejection, matching the
  passthrough rejected-status set) and other retryable failures keep the
  bounded same-candidate retry.
