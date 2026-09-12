# Native effort omission after a capability downgrade

Status: Proposed. A bounded continuation of #1119 at `bfd39a6b8cef2e70604dce82b2b9f26449aac99a`, retaining parent #1000 and the non-authorizing diagnostic gate. No production route, model selection, timeout, credential source or approval policy changes.

## Source and public contract

`contextual_orchestrator.reasoning_effort_profile.apply_request_profile` is an exported public helper. It validates a role profile and writes independently configured native effort, sampling and output controls into a supplied payload. Its documented contract says unsupported `abstain` and `error` fail closed, while explicit `omit` sends no unsupported effort field.

The complete published source was reconstructed and verified against blob `02e25e87e4ceb5e00584ac3445c59f5e602b3fa9`. On that source, a pre-existing `reasoning_effort` value survived when support was false and the selected fallback was `omit`. The function merely avoided adding a new field; it did not remove the old one. The same failure occurs after calling the helper first with supported=true and then supported=false on the same payload.

This is a reproduced public-function contract violation. Code search found its export and tests; the complete live-provider call graph was not established, so it is not asserted to be the cause of any particular production provider error.

## Minimal fix and preserved behavior

Remove `reasoning_effort` only in the validated unsupported+omit branch. Keep the supported native value, sampling controls, explicit output cap, seed, messages, tools, stream and model fields unchanged. Unsupported abstain/error still raise before payload mutation. With no profile, the existing compatibility behavior remains unchanged. The helper does not select another worker or switch a paid/free pool.

Native reasoning effort remains a request control, not a learned Fugu/TRINITY/Conductor policy. This repair neither replaces those algorithms nor makes the retained synthetic theta diagnostics empirical. `production_default_change_allowed` remains non-authorizing.

## Executed verification

Runtime: CPython 3.13.5; pytest 9.0.2. The tests import the complete exact leaf, not a substitute implementation. No provider, credentials or network calls are used.

- Fourteen new cases against the unchanged source: **5 failed, 9 passed**.
- Fourteen new cases after the minimal fix: **14 passed**.
- Combined with the twelve unchanged promotion-authority cases: **26 passed**, with warnings treated as errors.
- Changed function: **18/18 executable lines and 10/10 branch arcs** covered. Whole-module combined coverage is **75%**, not 100%; the complete integration suite was not run.

```sh
python3 -m coverage run --branch --source=contextual_orchestrator \
  -m pytest -q -W error tests/test_effort_omission_contract.py \
  tests/test_effort_promotion_authority.py
python3 -m coverage report -m
```

Source blob: `f876a176492d3ab51ce860bb5060a242c2f14613`.
New tests blob: `f3f99a5940764eac6d64df27cfc91e86701de6fe`.
Unchanged authority tests: `c815feae94153e9b32637893a999b3df2b6a821d`.

## Open delivery and adjacent ownership

Full exact-head CI, independent review and the parent's unresolved integration remain required. No merge, release or default promotion is claimed. The complete source and test diffs are preserved on the existing child branch rather than copied into a consumer.

CO #1117 owns request partition/capacity/replay controls. Central .github #2068 owns review-local evidence state and requires an actual trusted host session driver: its inspected read-only OpenCode profiles cannot execute the appended memory-write instructions. Automatic consumer integration, actual token accounting, nested-call admission, Rust runtime and immutable owner releases remain open. This one-field repair does not close those gaps.

Research distinctions and primary citations are maintained in `learned_policy_authority_20260910.md` and `request_partition_replay_20260910.md` on their respective owner PRs. Fugu-Ultra's training workflow length must not become an unexamined global call cap, and its access-list/tool-origin boundaries must survive outer request decomposition.
