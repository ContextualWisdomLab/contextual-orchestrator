# Fuzzing

The orchestrator consumes untrusted input at a handful of well-defined seams:
HTTP request bodies, agent-pool configuration, arbitrary prompt text, and trace
payloads that pass through secret/PII redaction. Those seams are fuzzed with two
complementary, permissively licensed tools.

| Tool | License | Role |
| --- | --- | --- |
| [Hypothesis](https://hypothesis.readthedocs.io/) | MPL-2.0 | Always-on property tests in the normal `pytest` suite (`tests/fuzz/`). Deterministic, cross-platform, shrinks any counterexample to a minimal repro. |
| [Atheris](https://github.com/google/atheris) | Apache-2.0 | Coverage-guided (libFuzzer) harnesses in `fuzz/`, run in a bounded CI job on Python 3.11. |

Both drivers call the same invariant checks in [`fuzz/targets.py`](../fuzz/targets.py),
so a bug found by either tool reproduces under the other.

## Targets

The surfaces were located with CodeGraph (`codegraph explore "parse decode
deserialize request config validate untrusted input"`):

1. **HTTP request body** — `server._coerce_json` / `_reject_unknown_keys` /
   `_validate_mode` / `_validate_messages`. Arbitrary bytes must normalise to a
   validated structure or raise `RequestError` / a JSON decode error — never an
   unhandled crash.
2. **Agent config** — `orchestrator.ModelAgent.from_dict`. Arbitrary decoded
   JSON must yield a well-typed `ModelAgent` or raise `KeyError`/`TypeError`/
   `ValueError`.
3. **Secret/PII redaction** — `orchestrator.redact_text` / `redact_value`.
   Never crashes, always returns `str`, is **idempotent** (re-redacting redacted
   text is a no-op), and preserves container shape.
4. **End-to-end orchestration** — `orchestrator.TaskOrchestrator.run` against
   `mock://` providers (fully offline). Arbitrary prompt text and mode must
   produce a JSON-serialisable record whose SSE framing round-trips.

## Running locally

Property tests (no native toolchain needed):

```bash
pip install -e '.[fuzz]'      # hypothesis
pytest tests/fuzz -q
```

Coverage-guided harnesses (needs Clang/libFuzzer; use Python < 3.13):

```bash
pip install atheris
python fuzz/fuzz_request_body.py  -max_total_time=60 fuzz/corpus/request_body
python fuzz/fuzz_agent_config.py  -max_total_time=60 fuzz/corpus/agent_config
python fuzz/fuzz_redaction.py     -max_total_time=60 fuzz/corpus/redaction
python fuzz/fuzz_orchestration.py -max_total_time=60 fuzz/corpus/orchestration
```

Seed corpora live in `fuzz/corpus/<target>/`.

## CI

`.github/workflows/fuzz.yml` runs the property tests on every push/PR and the
Atheris harnesses with a 60s-per-target budget on PRs (300s on the weekly
schedule / manual dispatch) to keep CI cost bounded. Crash inputs are uploaded
as artifacts.

## Background

For the theory behind coverage-guided greybox fuzzing, see
[`papers/fuzzing-art-science-engineering-manes-2019.pdf`](papers/fuzzing-art-science-engineering-manes-2019.pdf)
(Manès et al., *The Art, Science, and Engineering of Fuzzing: A Survey*).
