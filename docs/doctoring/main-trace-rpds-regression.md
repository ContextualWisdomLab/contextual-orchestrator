# Main regression: trace helper removal and fuzz pin drift

Protected `main` after PR #891 briefly carried a chat path that called the
removed `_trace_requested` helper: PR #888 had refactored trace handling to
`_validate_trace_request` + `_authorize_trace_access` + `_audit_trace_disclosure`,
but the structured/chat-response branch merged by #891 still invoked the old
method. Every structured chat or tool-plus-`response_format` request then raised
`AttributeError` and the server collapsed it to `500 internal_error` instead of
the intended `400 unsupported_trace_disclosure` fail-closed denial.

The fix keeps the already-validated `include_trace` value (computed earlier in
`do_POST` from `_validate_trace_request`) instead of re-calling the removed
helper, and aligns the two #891-era honesty tests with the fail-closed #888
contract (structured and single-agent tool passthrough reject undisclosable
trace disclosure; omission or `false` stays available to inference-only
callers).

The same merge also left `requirements.lock` at `rpds-py==0.30.0` while both
fuzz requirement files had drifted to `rpds-py==2026.6.3`; the fuzz and
Hypothesis CI jobs install `requirements.lock` and a fuzz file together, so pip
failed `ResolutionImpossible` before any test ran. Both fuzz files are restored
to the lock's `0.30.0` pin (same hash set), and the property fixture source
`.in` is updated to match so a future regen cannot drift it again.