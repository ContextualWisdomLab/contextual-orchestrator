# ADR 0007: Verbose/debug logging with a redaction safety net

## Status

Accepted.

## Context

Diagnosing why the gateway picked a given agent, why a provider call was
retried, or why a circuit breaker opened required adding temporary `print`
statements: the codebase had the `_LOGGER = logging.getLogger(__name__)`
convention in three modules (`server.py`, `telemetry.py`, `video_jobs.py`)
but no `logging.basicConfig` call anywhere, no CLI verbosity flag, and no
shared policy for what may be logged at which level. `orchestrator.py` (the
retry loop, circuit breaker, and evidence-based ranking in `_ranked_agents`)
and `model_discovery.py` (per-provider discovery attempts) had no logger at
all. This mirrors the gap ADR 0122 closed for span-based tracing: that ADR
correlates a request across providers via OpenTelemetry; this one gives an
operator or developer the internal *why* of one gateway decision without a
tracing backend, and does so as a runtime-observability decision in this
series rather than a product-planning one (see `docs/planning/adrs`'s own
distinction).

## Decision

Add a leaf module, `contextual_orchestrator/debug_logging.py`, that owns
level-name parsing (`parse_log_level_name`), one configuration entrypoint
(`configure_logging(level_name, redactor=None)`), and small pure log-line
formatters. No new dependency: this is stdlib `logging` only (see the
Ponytail entry added to `docs/library_research.md`). Because leaf modules may
not import anything else in this package, `orchestrator.py`,
`model_discovery.py`, and `server.py` can all depend on it without a cycle.

`configure_logging` calls `logging.basicConfig(level=level, force=True)` --
`force=True` is required because plain `basicConfig` is a no-op after the
first call in a process, which would otherwise make a second in-process CLI
invocation (a real pattern in this repo's own test suite) silently keep
whatever level the first call configured.

`contextual_orchestrator/__main__.py` resolves the effective level once, in
`_configure_logging_from_cli`, via a `parse_known_args` pre-scan that runs
before subcommand dispatch. This one call site covers
`register-credential`, `discover-models`, `check-fast-mlsirm`, one-shot
completion, and `--serve` uniformly. Precedence: explicit `--log-level` >
`--verbose`/`--debug` > `CONTEXTUAL_ORCHESTRATOR_LOG_LEVEL` > default
`WARNING` (the existing de facto stdlib default, kept unchanged so an
upgrade does not change anyone's stderr output by default). An invalid level
from either the flag or the env var fails closed with an argparse-style
`SystemExit(2)`; it is never silently ignored. Subcommand dispatch itself is
resolved by `_subcommand_token_index`, which skips past any recognized
leading `--log-level`/`--verbose`/`--debug` tokens (without removing them
from the argument list a subcommand's own parser sees) so that, e.g.,
`--verbose discover-models` still reaches the `discover-models` subcommand
instead of falling through to the one-shot completion parser with
`discover-models` parsed as the prompt.

New instrumentation lands at the previously silent decision points: the
provider retry loop (`_send_with_retry`/`_send_raw_with_retry`: per-attempt,
backoff, and a WARNING-level `provider_exhausted` line that fires without
`--verbose`, since a call that used its full retry budget is an actionable
operational event -- an immediate non-transient failure that never spent any
retry budget logs the distinct `provider_rejected_permanent` instead, chosen
by whether the loop broke from reaching the retry limit or from an early
non-transient break); the per-agent circuit breaker (`_record_failure` logs a
DEBUG line on every increment and a WARNING `circuit_opened` line only on the
edge transition into the open state; `_record_success` logs DEBUG only when
there was real breaker state to clear, to avoid a firehose on every healthy
call); and evidence-based ranking (`_static_rank_key`, `_measured_member_order`,
`_select_agent`). `model_discovery.py` gains per-provider `discovery_attempt`
/ `discovery_result` / `discovery_provider_failed` DEBUG lines (identifying
the account by provider name only -- never the KV credential name or value)
and one `discovery_complete` INFO summary. `server.py` gains one body-free
per-request INFO summary (method, bare path with any query string stripped,
status, latency, and the ADR 0122 session correlation hash -- factored into
a new `telemetry.session_id_hash()` shared by both surfaces; skipped
entirely on a keep-alive connection's closing call, which parses no new
request) and a DEBUG response-body summary that logs only an allowlisted
metadata shape, never the payload itself (see below).

Redaction is layered, and for the response-body summary specifically an
allowlist replaces "log the (redacted) payload" outright: every call site
that logs caller- or provider-derived string content wraps it in the
existing, unmodified `orchestrator.redact_text`/`redact_value` before
logging (e.g. `redact_text(str(exc))[:500]` in the retry loop) -- but
`redact_text`/`redact_value` only pattern-match a secret's in-string *value*
shape (e.g. `api_key=...` or `Bearer ...`) and never inspect the JSON key a
string is nested under, nor do they (nor should they) touch *ordinary*
response text at all. An earlier revision of this design logged the entire
already-redacted response payload at DEBUG, plus an additional
`debug_logging.redact_credential_shaped_keys` pass that replaces any dict
value under a credential-shaped key name (`key`, `api_key`, `token`,
`secret`, `password`, `credential`, `auth`, `private_key`, `pem`, and
similar) with `[REDACTED]` regardless of the value's own shape; independent
adversarial review (CodeRabbit, CWE-532) found that this still let ordinary,
non-credential response content -- `choices[].message.content`, tool-call
arguments, an `error.message` that can reflect caller-supplied input --
reach DEBUG output verbatim, which can carry PII or business-sensitive text
that has nothing to do with secrets. `debug_logging.response_metadata_for_log`
now extracts a small, fixed allowlist instead -- `has_error`, `model`,
`choice_count`, and numeric-only `usage` counts -- and that allowlisted dict,
not the payload, is what `redact_credential_shaped_keys` runs over
(defense-in-depth, in case a future allowlist field ever collides with a
credential-shaped key name) and what reaches the log line. This log-only
summary never changes what `_response_payload` returns to actual HTTP
callers. Finally, `configure_logging`'s optional `redactor` attaches a
`logging.Filter` to the handler `basicConfig` installs -- deliberately the
handler, not the Logger object, since a Logger-level filter does not run on
records propagating up from a child logger -- as a safety net for a call
site that forgets. Raw prompt or message text is never logged at any level,
only lengths, identifiers, and (for the response-body summary specifically)
allowlisted shape metadata: `redact_text` is documented to deliberately
leave PII alone, so this design does not lean on it to scrub content it was
never meant to scrub.

## Consequences

An operator can now answer "why did this request retry", "why did the
circuit breaker open on this agent", and "why did `orchestrator/free` pick
this model" from `--log-level DEBUG` / `--verbose` output, and get a
body-free per-request breadcrumb trail at `--log-level INFO`, without
touching OpenTelemetry. Layering value-pattern redaction, key-name-based
redaction, an allowlist for the one call site that would otherwise log
arbitrary content, and a handler-level safety net means a call site that
forgets one layer is still caught by one of the others, at the cost of a
little extra work per already-redacted DEBUG line when a redactor is
configured. Default (`WARNING`) behavior is unchanged: the new
DEBUG/INFO lines are opt-in, and the two new WARNING lines
(`circuit_opened`, `provider_exhausted`) are the only default-visible
additions, both operator-actionable rather than internal reasoning.

## References

Chickowski, E., et al. (OWASP Foundation). (n.d.). *Logging cheat sheet*.
Retrieved August 31, 2026, from
https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html

Kent, K., & Souppaya, M. (2006). *Guide to computer security log management*
(NIST Special Publication 800-92). National Institute of Standards and
Technology. https://doi.org/10.6028/NIST.SP.800-92

Python Software Foundation. (n.d.). *Logging HOWTO*. Python 3 documentation.
Retrieved August 31, 2026, from https://docs.python.org/3/howto/logging.html
