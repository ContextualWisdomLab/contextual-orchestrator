# Artifact runtime migration — Proposed, 2026-09-13

## Problem and minimal repair

CO artifact steps pin `330a01c490aca151604b8cf639adc76d48f6c5d4`, whose
[official action manifest](https://github.com/actions/upload-artifact/blob/330a01c490aca151604b8cf639adc76d48f6c5d4/action.yml)
declares Node 20. Source `7032bee94c85d4937ddad21de88bccd35051ff29`
changes only four pins on base `012beaacd0631f8cd3391c77744eeb626269b5de`.
Official `git ls-remote` resolves v7.0.1 to
`043fb46d1a93c77aae656e7c1c64a875d1fc6a0a`; its
[manifest](https://github.com/actions/upload-artifact/blob/043fb46d1a93c77aae656e7c1c64a875d1fc6a0a/action.yml)
declares Node 24. Paths, retention, failure behavior, permissions, triggers,
and concurrency remain unchanged. Hosted runner compatibility and successful
artifact publication remain CI acceptance requirements, not local-test claims.

## Ownership and alternatives

An inventory of 99 open PRs identified seven touching these workflows:
#1150 b8f9eb73, #1107 b0844bd8, #1091 6a32c676, #1090 2bf856cd,
#1067 a553b965, #1039 4002cf2d, #1002 27b6ba59. Their inspected hunks
change reporting, native wheel proof, benchmark budgets/bootstrap, triggers,
Node setup or runner labels; none changes these four pins. Preserve every
delta. No PR is superseded or closed by this repair.

The central owner is ContextualWisdomLab/.github. At inspected committed
revision `a1e4f9eeda5a37403abcf4e77c57cf8df8b9b07a`, python-security.yml
has no workflow_call entry point. The reusable exact-head coverage gate only
installs isolated coverage dependencies and does not preserve CO project locks,
wheel checks, fuzzing and all security jobs. Replacing the whole local workflow
with it would lose checks. Central dirty files were not changed or copied.

Migration remains an owner gap: define and release a reusable contract covering
these responsibilities, prove exact-head parity, then adopt a thin CO caller.
Do not require that future migration to repair the current runtime warning.
This infrastructure repair makes no psychometric accuracy or latency claim.

## Verification and continuation

At source 7032bee9, `actionlint .github/workflows/security.yml
.github/workflows/nim-benchmark.yml` produced no findings; the shared project
Python 3.14 interpreter ran `-m pytest tests/test_nim_benchmark_workflow_contract.py
-q -Werror`: **8 passed, 0.30s**, terminal exit 0.
No package dependencies were installed or changed. Git diff contains four pin
replacements only. Final-head CI, independent review and actual browser
inspection remain required before delivery claims.

Fresh main already uses workflow/repository/PR concurrency with cancellation
only for PR events; earlier local-quality naming observations came from the
older #1090 stack. NIM has only manual/schedule triggers and keeps its
non-cancelling serialization. Neither rule is rewritten here.

## Hosted metadata regression

Run 34706255388, job 103586722915, failed with 1 failed, 3,600 passed,
2 skipped in 149.43s. The repository security metadata test still expected
the old upload version comment; the earlier eight-test selection omitted it.
Update that expectation to the actual verified uses SHA, not the comment.
Include tests/test_repository_security_metadata.py alongside the NIM workflow
contracts in subsequent validation. This missed consumer assertion does not
justify reverting the runtime pin or suppressing the check. Running sibling
jobs were not restarted.
