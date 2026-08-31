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
- `server.py`'s `Handler.parse_request` (request-received: method, path with
  query string stripped and capped at 256 chars) and `.handle_one_request`
  (response-sent: same bounded method/path, plus status and latency).
  `log_request` -- the stdlib hook `send_response` calls the instant a
  response *starts*, before headers or any body/stream content are written
  -- only *captures* the status onto the handler instance; it does not log
  anything itself, so a streamed `chat.completion.chunk` response is timed
  by `handle_one_request` after the full response (every SSE frame) has
  actually been written, not at time-to-first-byte. See
  `tests/test_verbose_debug_logging.py::test_response_completion_log_covers_full_streamed_duration_not_first_byte`.
  `log_message` remains suppressed; these overrides emit through the module
  logger instead of reintroducing the default stderr line.
- `model_discovery.py`'s `discover_provider_models` (landed independently in
  #941, "secret-free provider discovery diagnostics"): per-account discovery
  skipped/started/failed/completed, naming only `provider_name` and a
  classified `error_code` -- verified secret-free and folded into this
  change's audited logger scope below rather than duplicated.

CLI wiring (`__main__.py`): a `--verbose`/`--debug` flag (single flag; this
codebase's existing flags are boolean `action="store_true"` switches, not a
tiered verbosity count) on the main `--serve`/CLI parser and, for consistency,
the `register-credential` and `discover-models` subcommand parsers.

`_configure_logging(verbose)` is a no-op when not requested, so default
output is unchanged. When verbose, it calls `logging.basicConfig(format=...,
force=True)` **without** a `level=` argument -- the root logger's own level
is deliberately left untouched -- and then calls `.setLevel(logging.DEBUG)`
on each logger individually named in `_VERBOSE_LOGGER_NAMES`:
`contextual_orchestrator.orchestrator`, `.server`, and `.model_discovery`.

This split matters and was not the first design: an earlier revision of this
change called `logging.basicConfig(level=logging.DEBUG, ...)`, which sets the
*root* logger's level. Python's per-logger effective level is inherited from
the nearest ancestor with an explicit level, so that raised every `.debug()`
call site in the process to visible -- including `openrouter_uptime.py`'s
pre-existing, unrelated, and never-rewritten
`logger.debug("Failed to fetch OpenRouter uptime for %s: %s", model_id, exc)`,
which logs a raw upstream exception via `%s`. Review caught this
(`tests/test_verbose_debug_logging.py::test_verbose_mode_keeps_openrouter_uptime_failures_silent`
is the regression). Setting a whole-package logger
(`"contextual_orchestrator"`) would reopen the identical leak through the
same inheritance mechanism, since `openrouter_uptime` is a child of it. The
fix enables DEBUG on each individually audited leaf logger instead, so an
unaudited call site elsewhere in this package -- or in a third-party
dependency sharing the process -- cannot become newly visible just because an
operator asked to see route/conduct/provider/discovery decisions.
`format=...` still applies process-wide (via the root handler every logger
propagates to), so WARNING+ output that was already visible by default keeps
consistent timestamp/level/name formatting; only which loggers reach DEBUG is
scoped. `force=True` lets a later call (e.g. a test invoking `main()` more
than once in one process) replace an earlier handler instead of silently
no-op'ing, matching `logging.basicConfig`'s documented purpose for a process
that decides its logging configuration once at startup.

An env var, `CONTEXTUAL_ORCHESTRATOR_VERBOSE` (truthy: `1`/`true`/`yes`/`on`,
case-insensitive), provides the same default-value-from-environment pattern
this file already uses for `CONTEXTUAL_ORCHESTRATOR_STATE_DB`,
`CONTEXTUAL_ORCHESTRATOR_AGENTS_DB`, `CONTEXTUAL_ORCHESTRATOR_CLEARFOLIO_URL`,
and `CONTEXTUAL_ORCHESTRATOR_PROVIDER_CA_BUNDLE`: read via `os.environ.get()`
as an `argparse` default exactly once, at process startup, inside `main()`'s
(or a subcommand's) own parser construction -- never read again afterward,
and never read at HTTP request-handling time. This is bootstrap-transport
env use, the same carve-out `AGENTS.md`'s "KV, not env" rule already grants
those four precedents: the rule targets *runtime* config and provider secrets
resolved from `os.getenv` while serving a request, not a one-shot CLI
process's own startup flags. Turning this on for an already-deployed server
still requires setting the env var and **restarting the process** -- exactly
like those four precedents, and unlike a KV-backed runtime setting, this is
not a live/dynamic toggle. No SIGHUP/hot-reload handler is added, and no
`kv_config.py`-backed dynamic setting was built for it either; both are out
of scope for a debugging aid, not an observability platform (OpenTelemetry
already covers that), and would add complexity a one-shot process-restart
flag does not need.

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
- **Per-request opt-out / sampling.** Once enabled, every request on the
  process sees DEBUG output from the audited loggers, like every other
  `--serve` flag in this file. A noisy per-request knob was judged
  unnecessary complexity for a debugging aid.
- **The root logger's level, and any not-individually-audited logger.**
  Verbose mode raises `.setLevel(logging.DEBUG)` only on the three loggers
  named in `_VERBOSE_LOGGER_NAMES`. It does not touch the root logger's level
  or a whole-package `"contextual_orchestrator"` logger, and it does not
  enable `telemetry.py`, `video_jobs.py`, or `openrouter_uptime.py`'s loggers
  -- the last of which has a pre-existing `.debug()` call site that logs a
  raw exception and was deliberately left both unaudited and unreachable by
  this change rather than silently rewritten as a side effect.
- **Live/dynamic toggling without a restart.** The env var is read once at
  process startup, identically to this file's other four env-backed CLI
  defaults; it is not a `kv_config.py`-backed runtime setting a running
  server can pick up without restarting.

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
