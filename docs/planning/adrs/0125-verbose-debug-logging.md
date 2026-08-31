# ADR 0125: Verbose/Debug Logging for the Route/Conduct/Provider Control Flow

- Status: Accepted
- Date: 2026-08-31

## Context

Operators debugging a route-vs-conduct decision, a provider retry/failover, or
a per-agent circuit-breaker trip had no runtime visibility: `telemetry.py`
imports `logging` and has exactly one `.debug()` call site
(`configure_telemetry`'s "OpenTelemetry is not configured without a KV store"),
and nothing in the process ever calls `logging.basicConfig`, so no `.debug()`
call anywhere in the package was ever actually observable. `server.py`
separately overrides `log_message` to suppress `BaseHTTPRequestHandler`'s
default per-request stderr line, "to keep service output structured" -- a
deliberate choice this change preserves rather than reverts. The CLI
(`__main__.py`) had no `--verbose`/`--debug` flag and no `LOG_LEVEL`-shaped
env var.

OpenTelemetry tracing (`telemetry.py`) already exists for exported, sampled,
allowlisted-attribute observability. This is a different, complementary need:
ad hoc local/production stderr visibility into *why* the orchestrator made a
specific control-flow decision on one run, without standing up a collector.

## Decision

Use the stdlib `logging` module already imported by this package (Ponytail:
no new dependency). Each of `orchestrator.py`, `server.py`, and (already
present) `telemetry.py`/`video_jobs.py`/`openrouter_uptime.py` keeps its own
module-level `_LOGGER = logging.getLogger(__name__)`. New `.debug()` call
sites (silent unless DEBUG is enabled, so zero behavior change by default) are
added at the control-flow points that matter for debugging:

- `TaskOrchestrator._dispatch`: the route-vs-conduct decision (mode, model,
  chosen path).
- `TaskOrchestrator.route_once` / `.conduct`: each attempt/step transition
  (attempt or step index, role, agent id, access-list scope, served agent id,
  latency, whether failover occurred) -- never the prompt, the accessed prior
  outputs, or the model's answer.
- `TaskOrchestrator._invoke`: which candidate is being tried and why a prior
  one failed (`ToolFailureDecision.kind`/`.action`/`.reason_code` -- bounded
  enum/string values, never the raw exception message, which can echo
  provider response text).
- `TaskOrchestrator._record_failure` / `_circuit_open` / `_record_success`:
  circuit-breaker state transitions (opened, half-open, closed) by agent id.
- `ModelClient._send_with_retry` / `_send`: each provider attempt (agent id,
  model, provider, host) and each retry/backoff decision (attempt number,
  delay, and the exception's *class name* only -- never `str(exc)`, which for
  an `HTTPError` can carry the upstream response body).
- `server.py`'s `Handler.parse_request` / `.log_request`: request-received and
  response-sent (method, path with query string stripped and capped at 256
  chars, status, latency) -- these are the two stdlib hooks
  `BaseHTTPRequestHandler` already calls on every request/response, so no new
  call sites are threaded through `do_GET`/`do_POST`. `log_message` remains
  suppressed; these two overrides emit through the module logger instead of
  reintroducing the default stderr line.

CLI wiring (`__main__.py`): a `--verbose`/`--debug` flag (single flag; this
codebase's existing flags are boolean `action="store_true"` switches, not a
tiered verbosity count) on the main `--serve`/CLI parser and, for consistency,
the `register-credential` and `discover-models` subcommand parsers. It calls
`logging.basicConfig(level=logging.DEBUG, format=..., force=True)` -- a no-op
when not requested, so default output is unchanged. The format includes
`%(asctime)s`, `%(levelname)s`, and `%(name)s` per call site. `force=True`
lets a later call (e.g. a test invoking `main()` more than once in one
process) replace an earlier configuration rather than silently no-op, matching
`logging.basicConfig`'s documented purpose for a process that decides its
logging configuration once at startup.

An env var, `CONTEXTUAL_ORCHESTRATOR_VERBOSE` (truthy: `1`/`true`/`yes`/`on`,
case-insensitive), provides the same default-value-from-environment pattern
this file already uses for `CONTEXTUAL_ORCHESTRATOR_STATE_DB`,
`CONTEXTUAL_ORCHESTRATOR_AGENTS_DB`, `CONTEXTUAL_ORCHESTRATOR_CLEARFOLIO_URL`,
and `CONTEXTUAL_ORCHESTRATOR_PROVIDER_CA_BUNDLE` -- read once at process
start, so a deployed server can turn on DEBUG logging without an operator
having to edit its CLI invocation, at the cost of still needing a restart.
No SIGHUP/hot-reload handler is added; that is out of scope for a debugging
aid, not an observability platform (OpenTelemetry already covers that).

## Explicitly excluded

- **Prompt/response/tool-output content.** No log record at any level
  includes message content, the accessed-prior-step text, or a model's
  answer. Debugging with real content is OpenTelemetry's job today
  (`traced`/`annotate_current_span`'s `_ALLOWED_ATTRIBUTE_KEYS` allowlist) and
  stays that way; this change does not extend that allowlist or invent a
  second one for logging.
- **Credentials.** No log record includes an API key, an `Authorization`
  header, or any other header. Provider request logging names the agent,
  model, provider, and destination host only.
- **Raw exception text.** Retry/backoff/failure-classification logs record
  the exception's class name and, where one already exists as a bounded
  value, the classified failure kind/action/reason code -- never `str(exc)`.
- **A new logging framework or log shipping.** stdlib `logging` only, no
  structured-logging-as-a-service dependency, no rotation, no shipping. That
  remains this repository's OpenTelemetry integration's job.
- **Per-request opt-out / sampling.** DEBUG is process-wide once enabled, like
  every other `--serve` flag in this file. A noisy per-request knob was judged
  unnecessary complexity for a debugging aid.

## Consequences

- Operators can now see, at DEBUG, exactly which agent an orchestration run
  is trying, why a retry/failover happened, and when a circuit trips or
  resets -- locally with `--verbose`, or on a deployed server via
  `CONTEXTUAL_ORCHESTRATOR_VERBOSE=true` and a restart.
- Default (non-verbose) behavior is unchanged: no new stdout/stderr noise, no
  new dependency, no change to the existing `log_message` suppression.
- `tests/test_verbose_debug_logging.py` is a regression contract: DEBUG
  entries appear only when enabled, and a fed-through fake secret/prompt is
  asserted absent from captured log output at every one of the call sites
  above.

## References

Python Software Foundation. (2026). *logging — Logging facility for Python*.
https://docs.python.org/3/library/logging.html
