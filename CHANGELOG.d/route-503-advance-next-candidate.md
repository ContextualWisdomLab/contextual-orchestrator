- Virtual `route_once`/`conduct` routes advance to the next eligible
  candidate after an explicit provider HTTP 503 instead of replaying the
  same candidate first, so a pool where every route returns 429/503 is
  attempted once per candidate before the last classified error is returned.
  A 503 still counts toward the provider health circuit; 502/504 and other
  retryable failures keep the bounded same-candidate retry.
