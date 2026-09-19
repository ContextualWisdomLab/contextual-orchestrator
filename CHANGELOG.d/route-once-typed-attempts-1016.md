Non-streaming `route_once` failover now records the same typed per-attempt
evidence as structured synthesis and `stream_route` (issue #1016): each failed
candidate in the shared `_invoke` loop carries `outcome`
(`retryable_transport`, `request_too_large`, `deadline_exceeded`, or
`fail_closed`), `error_code`, `provider_status`, `retryable`, and `transport`
on `orchestration.route.attempted[]`. A successful first attempt still omits
route evidence entirely so no empty failed rows are invented.
