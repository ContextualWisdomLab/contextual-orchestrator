# JSON fuzz corpus delivery

The agent-config and reasoning-effort harnesses consume serialized JSON bytes,
matching their checked-in corpora and the existing rater-observation harness.
`FuzzedDataProvider.ConsumeUnicodeNoSurrogates` is not a UTF-8 decoder: it consumes
an encoding selector byte. With a JSON object's opening `{`, the remaining text
loses its opening brace and is rejected before reaching the target.

The original six seeds reproduced this failure with Atheris 3.1.0 on Linux
x86_64/Python 3.12.13. The CP312 wheel SHA-256 is
`ec5e11f21a4c197fe91f7aea2b2de88e623c73a21fc07b105ac6329a1588457b`,
matching `fuzz/requirements-atheris.txt`. Its Linux-only distribution is not a
reason to downgrade the CI pin when developing on macOS.

The harnesses now pass bytes directly to `json.loads`; malformed encoding/JSON
and excessive nesting return without dispatch. Corpus regressions in
`tests/fuzz/test_json_corpus.py` verify unchanged values reach each target.
The existing Security fuzz job installs Atheris and runs `pytest tests/fuzz -q`.
When Atheris is absent from a general test environment, this dedicated runtime
check is explicitly skipped; a broken installed runtime is not suppressed.

Missing native sanitizer hooks are a separate unresolved diagnostic in
[#1164](https://github.com/ContextualWisdomLab/contextual-orchestrator/issues/1164).
Seed delivery, mutation coverage, crash reporting and hosted gate success are
separate acceptance claims. No warning suppression or corpus deletion is used.

## Local validation boundary

The Linux x86_64 check under QEMU initially attempted the full repository lock.
`fast-mlsirm` metadata preparation failed when `rustc -vV` received SIGSEGV;
Rust bootstrap also reported a missing C linker. No tests ran in that attempt.
This does not establish a failure on the native hosted Linux runner.

The corpus unit check uses locked Atheris/pytest dependencies and loads the real
harnesses with only their domain callbacks replaced by capture functions. It
checks byte parsing and dispatch, not domain-parser correctness, native numerical
code, or libFuzzer's mutation/crash-reporting behavior. Existing property tests
and the complete Security job retain those separate responsibilities.
