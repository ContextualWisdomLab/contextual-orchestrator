Type the single-worker streaming fallback's per-attempt evidence the same way the
structured-synthesis candidate loop already does (issue #1016, rows 2 and 4): each
failed candidate recorded in `stream_route`'s persisted trace before the served one
now carries `outcome` (`retryable_transport`, `request_too_large`,
`deadline_exceeded`, or `fail_closed`), `error_code`, `provider_status`,
`retryable`, and `transport`, alongside the existing prose `subtask`/new `reason`
field -- prose is no longer the only signal a caller can act on. `deadline_exceeded`
reuses PR #1053's `model_timeout` error code rather than inventing a second
vocabulary. Both fallback paths now share one small helper,
`_typed_attempt_entry`, instead of each building its own dict. The
`orchestration.route`/`route.attempted[]` shape this documents was previously
internal and undocumented; `api_contract.py` now carries it as a versioned
(`0.3.0`) `OrchestrationRoute`/`OrchestrationRouteAttempt` schema, and
`test_api_contract.py` validates a real structured-synthesis failover and a real
streaming failover against it.
