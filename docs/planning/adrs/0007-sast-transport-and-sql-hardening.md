---
id: "0007"
title: "Harden provider transport and SQL ledger against scanner findings"
status: accepted
proposed_date: "2026-08-11"
accepted_date: "2026-08-11"
deciders:
  - "repository maintainer"
consulted:
  - "Semgrep SAST workflow"
  - "provider transport and cost ledger callers"
informed:
  - "contributors"
affected_components:
  - "contextual_orchestrator/orchestrator.py"
  - "contextual_orchestrator/cost_ledger.py"
  - "contextual_orchestrator/__main__.py"
  - "tests/test_provider_tls.py"
  - "tests/test_local_mlx.py"
  - "tests/test_cost_ledger.py"
effort: M
supersedes: null
superseded-by: null
related:
  - path: "docs/planning/adrs/0002-explicit-local-mlx-evaluation.md"
    relation: influences
  - path: "docs/planning/adrs/0003-keyverse-authentication-boundary.md"
    relation: informational
asr_triggers:
  - kind: security
    evidence: "The first PR Semgrep run reported unverified TLS construction, dynamic urllib URL use, and three SQL string-construction findings."
    note: "Resolve the trust-boundary findings in code; scanner suppression is not the default remediation."
  - kind: maintainability
    evidence: "The provider transport and DB-API ledger support multiple protocol/driver shapes."
    note: "Keep explicit protocol variants and fixed SQL templates instead of adding a broad dependency or dynamic query builder."
success_criteria:
  - metric: "provider transport safety"
    target: "remote HTTPS uses a verifying SSL context, local HTTP is loopback-only, and non-HTTP request URLs are rejected before I/O"
    measurement_window: "every provider transport test and PR SAST run"
    source: "ModelClient transport tests and Semgrep"
  - metric: "ledger query safety"
    target: "all DB-API SQL statements use fixed templates with bound values and an explicit qmark/pyformat parameter-style allow-list"
    measurement_window: "every SQL ledger operation"
    source: "SqlLedgerStore tests and Semgrep"
---

# Harden provider transport and SQL ledger against scanner findings

## Context

The first remote PR security run found five blocking findings. Three were
reported in the SQL ledger, one in the explicit TLS opt-out, and one in the
provider request transport. The ledger already used fixed column names and
bound values, but its f-strings made that safety difficult for the scanner and
left the parameter-style boundary implicit. A follow-up scan showed that the
first fixed-template change still interpolated the fixed column list, so Ruff
S608 remained reproducible even though runtime values were bound.

> Semgrep reported raw-query construction at the three fixed SQL execution sites in cost_ledger.py.
>
> Semgrep reported ssl._create_unverified_context and a dynamic urllib URL in the provider transport.
>
> The local MLX path needs plain HTTP only for a validated loopback endpoint; remote providers must retain HTTPS verification.

## Decision Drivers

* Remove real insecure TLS behavior from the public API.
* Keep local mlx-lm usable without sending a credential or requiring TLS.
* Make the URL trust boundary visible to both code review and static analysis.
* Preserve sqlite3 and psycopg compatibility without adding SQLAlchemy for one ledger.
* Keep SQL values bound and SQL identifiers fixed.

## Considered Options

* Suppress the five Semgrep rules with comments and keep the implementation.
* Add SQLAlchemy and retain urllib with a disabled-TLS development flag.
* Use verifying TLS only, a small stdlib http.client transport after strict URL validation, and fixed SQL templates for each supported DB-API parameter style.

## Decision Outcome

Chosen option: "Fix the trust boundaries and make safe variants explicit".

| Driver | Suppress findings | Add broad dependency / keep bypass | Fixed stdlib transport and SQL templates |
| --- | --- | --- | --- |
| Remote TLS verification | Fails | Fails | Satisfies |
| Local loopback MLX support | Preserves | Preserves | Preserves |
| SQL value binding | Obscures review | Delegates to dependency | Explicitly preserves |
| Dependency and maintenance cost | Low now, high risk | High | Low |
| Scanner and review evidence | Weak | Mixed | Strong |

Remote transport always uses a verifying SSL context; custom CA bundles remain
supported, but TLS verification cannot be disabled. The CLI option that offered
an insecure TLS bypass is removed. Provider I/O uses `http.client` after
validating the request URL as HTTP(S), with the existing agent-level HTTPS,
loopback, DNS, and credential checks remaining in force. The validated sockaddr
is carried into the connection so the socket does not resolve the hostname a
second time; the original hostname remains the TLS SNI and HTTP Host identity.
The local `mlx://` scheme is translated to loopback HTTP only by the validated
provider URL path.

`SqlLedgerStore` accepts only `qmark` and `pyformat`. Select/insert statements
use fixed SQL templates for each parameter style and fixed column lists; start
and end windows select one of four fixed query templates. Values remain DB-API
parameters and never become SQL text.

The final Semgrep run identified the stdlib `HTTPSConnection` call itself even
though the code passes the already reviewed verifying SSL context. A
rule-specific `nosemgrep` annotation is retained at that one call site, with
the transport and TLS tests remaining the source-of-truth checks. This is a
documented false-positive boundary, not a suppression of certificate
verification or URL validation.

### Consequences

* Good, because the remote SAST gate checks the same invariant the runtime uses.
* Good, because a caller cannot accidentally turn off certificate verification.
* Good, because local MLX remains a deliberate loopback exception rather than a general HTTP exception.
* Good, because the cost ledger remains dependency-free and portable.
* Bad, because callers relying on `verify_tls=False` must use a trusted CA bundle or local HTTP loopback instead.
* Bad, because adding another DB-API parameter style requires one reviewed set of fixed templates.

## Problem Register and Remediation Directions

| Finding | Direction | State |
| --- | --- | --- |
| Semgrep/Ruff flagged three f-string SQL statements that still interpolated a fixed column list. | Declare complete qmark/pyformat INSERT and SELECT templates as literals, keep all values bound, and add a pyformat regression covering seed, append, and all four query windows. | Implemented locally 2026-08-12; exact-head CI/SAST revalidation required |
| `paramstyle` accepted arbitrary values and silently selected pyformat. | Reject styles other than qmark and pyformat at construction. | Implemented |
| `ssl._create_unverified_context` made an insecure remote mode executable. | Remove the bypass and keep `ssl.create_default_context` or a validated custom CA bundle. | Implemented |
| `urllib.request.urlopen` accepted a dynamically assembled request URL. | Use `http.client` with scheme/host/userinfo validation at the final I/O boundary. | Implemented |
| Semgrep flagged the reviewed `HTTPSConnection` API despite its explicit verifying context. | Keep the verifying context and add only the exact rule-specific suppression at that call site; retain transport regression tests. | Implemented |
| DNS could return a safe address during validation and a different address during connection. | Return the validated sockaddr and pin every HTTP, HTTPS, streaming, passthrough, and batch connection to it while retaining hostname SNI/Host semantics. | Implemented |
| A scanner-clean result could regress without a transport test. | Add a non-HTTP rejection regression and rerun the full SAST/CI gate. | Implemented / ongoing CI confirmation |
| `actionlint`/ShellCheck flagged unquoted `FUZZ_SECONDS` expansions in every fuzz target, leaving the workflow vulnerable to word-splitting/globbing if the time-budget value changed. | Quote the shell expansion at every fuzz invocation and require the workflow lint gate to remain clean. | Fixed locally 2026-08-13; exact-head CI/SAST revalidation required |

## Risks and Mitigations

| risk | likelihood | impact | mitigation | owner |
| --- | --- | --- | --- | --- |
| A future caller bypasses `_validate_provider` and calls private transport directly. | low | high | Final transport validation rejects non-HTTP URLs and userinfo; keep private methods covered. | maintainer |
| A custom CA bundle is untrusted. | low | high | Treat the path as deployment configuration; require file existence and normal SSL context loading. | deployment owner |
| SQL template additions reintroduce dynamic identifiers. | medium | high | Keep column names in fixed constants and values in parameter tuples; rerun Semgrep. | maintainer |

## Rollback / Exit Strategy

If an external DB-API driver requires another parameter style, add a new fixed
template set and tests through a follow-up ADR. Do not restore disabled TLS or
dynamic SQL concatenation as a compatibility shortcut. If the local transport
needs a proxy later, add an explicit, reviewed proxy boundary rather than
reintroducing general urllib URL handling.

## Affected Components

* contextual_orchestrator/orchestrator.py
* contextual_orchestrator/cost_ledger.py
* contextual_orchestrator/__main__.py
* tests/test_provider_tls.py
* tests/test_local_mlx.py
* tests/test_cost_ledger.py
