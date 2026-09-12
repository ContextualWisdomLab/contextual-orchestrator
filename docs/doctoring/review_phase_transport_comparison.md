# Free review transport: deployed-source comparison

Recorded 2026-09-12. This is a bounded diagnostic record, not a deployment
receipt, production validation, or a new routing-policy decision.

## Incident and evidence boundary

The coordinator inspected GitHub Actions run `34688188671`, job
`103539568718`, for `.github` PR #2052. The job reported HTTP 502 with
`provider_connection_error`. Its actual job log, lines 980–981, records
vendoring and installing dependencies for contextual-orchestrator revision
`414f22973658c4ddc3d4320fcf7acd9b4e8ba991` at 10:34:23–10:34:26.
The trusted workflow revision was
`fb17ef556f94f673234aa557254ae52779e9a7b0`.

The supplied local evidence directory was
`/tmp/cwl-noema-evidence.8M4Tel/`. Its sidecar stderr records repeated Flash
and Pro attempts, circuit opening/reset/clearing, and a final approximately
90-second TimeoutError. Preflight reports 24 candidates, 16 probed, five
ready, two deferred, and nine rejected. This disproves the hypothesis that
only one internal attempt occurred. Readiness is not proof that every ready
candidate satisfied every later role/request constraint.

The source pin is established by the job log. A runtime image/package digest
and request-correlated terminal role are not established. The terminal call
cannot be identified as final synthesis solely from these logs. Missing
provider usage remains unavailable, not zero.

## Frozen unit comparison

Tests were committed **before execution** in
`8065ada18b5e0c785446f2e081b26d5cf60d0aca`, based on
`50e1b0d0a7eddc0f866ab69162d6cf098efe693f`. The test is
`tests/test_passthrough_provider_failover.py::test_free_review_phase_timeout_preserves_eligible_sibling`.
It reuses the free-tagged two-candidate fixture pattern, executes actual
conduct stages, passively records planner/stage calls, and injects an
immediate unit TimeoutError. There is no sleep or provider request.
The unavailable calibration resolver remains fail-closed; a test double is
not a production judge approval or a real review-provider integration.

| Source | Generated-planner injection | Final structured-synthesis injection |
| --- | --- | --- |
| `50e1b0d0` with test commit `8065ada1` | PASS: planner never entered | PASS: primary then eligible free sibling |
| `414f2297` | PASS: planner never entered | FAIL: `ProviderUpstreamError`, sibling not reached |

Current-source pytest session `72922` completed with **2 passed, 67
deselected in 1.50s**. These are passing current regression tests, not RED
results. Both versions route `FREE_MODEL` to fixed planning even when the
generated-planning policy is configured: old source lines 6504–6506, current
source lines 7231–7234. Therefore the armed planner exception never executes;
this test cannot establish generated-planner recovery.

For the old-source comparison, a detached worktree at
`/tmp/co-review-phase-deployed-20260912` preserved the source unchanged.
Whole-module pytest collection failed because that old revision lacks the
unrelated newer `_is_ambiguous_passthrough_transport_failure` import used by
other tests. The fallback harness parsed the frozen committed test module
with stdlib `ast`, selected only `SequencedProxyClient` and the test function,
and executed those unchanged definitions with their explicit dependencies.
It invoked both parameter cases with `pytest.MonkeyPatch.context()`.
The printed imported source was
`/private/tmp/co-review-phase-deployed-20260912/contextual_orchestrator/__init__.py`.
The harness caught and printed failures for comparison, so its zero shell
exit status must **not** be read as a passing old-source test run.

Old-source final synthesis reaches `send_synthesis`, then raises the
classified exception at `orchestrator.py:4848`. That branch advances on size
or selected stale-model failures but not this retryable transport failure.
Current code advances eligible virtual synthesis candidates on
`classified.retryable`. This is a reproduced unit-level source difference,
not proof of the incident's terminal phase or sole cause.

## Existing repair and next action

The repair already exists in commit
`1c61eff2da012382255bf8b4e1aa6dd0d6dd05ca`:
“fix(gateway): fail over structured 502 onto the next free worker.”
The coordinator independently confirmed [PR #1094](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/1094)
MERGED at `2026-09-09T23:24:35Z`, head prefix `73338d21`, merge
`9334dc91aaf853b758077e983517a822b6b21edb`.
Local ancestry places the repair in recorded `origin/main`
`012beaacd0631f8cd3391c77744eeb626269b5de`.

No duplicate runtime fix is warranted by this comparison. Release/sidecar
adoption should be checked against the existing repaired owner revision,
with immutable artifact identity and correlated execution evidence before
claiming recovery. The coordinator found no listed GitHub releases; this
does not prove that no registry package exists.

No paid fallback, consumer retry, timeout/default change, eligibility
relaxation, push, or PR mutation was performed. HTTP integration, live
provider behavior, final rendered-document visual inspection, and incident
causal certainty remain unverified by this bounded exercise.

Additional coordinator checks: `gh release list --limit 5` for this repository
returned no entries; local `git tag --contains 1c61eff2` returned none (local
tag inventory only); the public PyPI endpoint
`https://pypi.org/pypi/contextual-orchestrator/json` returned HTTP 404 in a
separate request. These checks do not rule out alternate distribution names
or private registries. No immutable released adoption has been verified.

## Exact protected-merge adoption check

The minimal candidate `9334dc91aaf853b758077e983517a822b6b21edb` was checked
in detached `/tmp/co-review-phase-merge-20260912`. The unchanged selected
test definitions described above passed both cases. Its own
`tests/test_review_gateway.py` passed **13 tests in 0.81s**. The ancestry
check against `012beaacd0631f8cd3391c77744eeb626269b5de` returned exit 0.
The generated-planner case still means no planner invocation, not recovery.

The central launcher was read at `.github` PR #2052 head
`68daf0f61d2afc0ebf68aa260713b2e481f5112d`, path
`scripts/ci/contextual_orchestrator_review_sidecar.sh`. It installs only the
hash-locked dependencies, then imports the selected CO source. The old and
candidate `requirements.lock` files have identical SHA-256
`c80752a4c6bbbc1bc9b0cb2b938831693a88dfdca7d1130bb4c00e2f9fe21345`.
The changed project dependency URL does not participate in this install path.

The exact import statement and unchanged startup heredoc were executed with
`PYTHONPATH=/tmp/co-review-phase-merge-20260912:/private/tmp/cwl-pr2052-current`,
the isolated interpreter
`/tmp/co-cache-wheel-4bc96045.C4cqDg/installed/bin/python`, and working
directory `/tmp`. The imported source path was printed and verified. The
startup body SHA-256 was
`3dc3b5bffb95f90ba9ef1db1dbe93003def994e4d063637420ed9bbe0645b178`.
Session `83034` exited 0 with `IMPORT_AND_STARTUP_CONTRACT_PASS`.
This exercised real loopback HTTP rejection above the body limit, acceptance
above 64 KiB, exact tool-description byte preservation, and connection/server
cleanup. Provider responses were test doubles; no credentials or provider
requests were used. This did not reinstall dependencies or execute the full
provisioning shell. It proves this bounded startup contract, not hosted CI,
registry release, live discovery, or recovery of the original incident.

### Rendered-document inspection

Source `49362265` was rendered at `http://127.0.0.1:18773/transport` in the
actual in-app browser, English, 1265 × 712 viewport. Four successive viewport
captures were directly opened: introduction/evidence boundary, source
comparison table, existing repair/limitations, and exact-merge startup proof.
Table cells, long hashes/paths, paragraph spacing, contrast and vertical
scrolling were legible without observed clipping or overlap. The captures
are retained in this task's visual tool results, not as repository image
files. This supersedes only the earlier uninspected-document statement;
mobile, other locales, application UI states and live deployment remain
outside this bounded inspection. No Figma artifact was supplied for this
diagnostic document.
