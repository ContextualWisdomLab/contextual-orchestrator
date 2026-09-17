# Main-based integration of effort evidence and promotion guards

Status: Proposed; source repair and local regression evidence, not a released product.
Date: 2026-09-12.
Owner: ContextualWisdomLab/contextual-orchestrator.
Integration branch: `fix/effort-authority-main-20260912`.

## Problem and selected integration boundary

PR #1119 contains three independently useful guards: caller-editable synthetic diagnostics cannot authorize production-policy promotion; explicit unsupported-provider omission removes stale native effort; and only literal boolean True proves native-effort capability. These changes do not depend on the broad numerical/routing changes in parent #1000.

The historical child at `4caac373ae861f5892acb2075cd97f38b097573f` had zero GitHub check runs and zero workflow runs. Its inherited Tests workflow selected only PRs targeting main, excluding this stacked child. Current protected main has replaced those obsolete separate CI/Fuzz workflows with Security and Quality. Waiting or restoring the obsolete workflows would not repair the integration boundary.

The successor therefore starts at protected `main@012beaacd0631f8cd3391c77744eeb626269b5de`, tree `b840744cfb6a38681d20fd7df315dafce9fbf2db`, and carries all nine unique #1119 path deltas. It does not merge the unresolved #1000 tree, rewrite either history, or retire either predecessor. The original PR stays available until complete successor verification and protected delivery. Existing Security and Quality and organization-required workflows remain unchanged; no new CI, special passing status, self-modifying driver, release or provider call is added.

## Complete unique-delta carryover

| #1119 path | Successor treatment |
| --- | --- |
| `contextual_orchestrator/reasoning_effort_profile.py` | Preserve every authority, omission, typed-capability and explanatory change; additionally retain current main's nullable output-ceiling behavior. Integrated blob `2698a4c3e7f82070d865e96406c4071e4e068c50`. |
| `AGENTS.md` | Apply only the corrected issue-568 authority bullet to complete current main, preserving its newer transport, tool-handoff, correlation and credential guidance. Integrated blob `865af2195321fa7100e97b9e2a22393265495aba`. |
| `tests/test_reasoning_effort_profile.py` | Carry the complete two-hunk correction; current-main preimage matches `d3389078c5167969320a89585d5bdcfba1838c3c`, successor `d210ffe76fe5e20cb8bb3c8294b9f9ef6aabef59`. |
| `tests/test_effort_capability_evidence.py` | Identical blob `ca40abf2f13747e5cdd543a480f6de6ef5c9424b`. |
| `tests/test_effort_omission_contract.py` | Identical blob `f3f99a5940764eac6d64df27cfc91e86701de6fe`. |
| `tests/test_effort_promotion_authority.py` | Identical blob `c815feae94153e9b32637893a999b3df2b6a821d`. |
| `docs/doctoring/learned_policy_authority_20260910.md` | Identical historical research and reconstruction record `9c26e4cd661cb95c01ca8f29d006ed62f92a4c71`. |
| `docs/doctoring/effort_omission_contract_20260910.md` | Identical historical omission record `ccc34b97d7a922f1a54ba5601028cb84bd7eadfc`. |
| `docs/doctoring/effort_capability_evidence_20260912.md` | Identical child RCA and verification record `7057a24717925fa9e7728c222ef4e15d163e3940`. |

The historical records retain their original child/base/head/coverage scope. This integration record supplies the new main-based identity; it does not relabel historical test runs as current results.

## Current-main behavior that must not regress

Current main changed `default_max_output_tokens` to `int | None`. Without a profile, an unknown output ceiling must not add `max_tokens: null` or invent a limit. Copying the old child file wholesale would have lost this change. The integration instead combines the child delta with this exact main contract and retains the corresponding explanatory paragraph.

Six additional cases in `tests/test_effort_main_output_contract.py` cover unknown ceiling with True/False/None capability, existing explicit request limit, explicit supported profile without a default ceiling, and stale-effort omission with an unknown ceiling. They preserve the preceding omission, capability and non-authorizing-promotion contracts, rather than altering a routing or token-allocation policy.

## Fresh RED and GREEN evidence

The complete predecessor source was reconstructed and verified against Git blob `7f8fedd9ca5ea07282bf122bac82471cc8f3b176`. The test-first successor commit is `9e7359fb16c1bd6e8e052be600d84ada10ceea97`.

Four standalone regression modules against the unchanged main source: **67 failed / 22 passed**. Against the integrated source: **89 passed**, repeated with warnings treated as errors after verifying the complete source/test blob identities. The changed helper covers **20/20 executable statements and 14/14 branch arcs**. Whole-module coverage is **75%**, not 100%.

```sh
python -m coverage run --branch --source=contextual_orchestrator -m pytest -q -W error \
  tests/test_effort_capability_evidence.py \
  tests/test_effort_omission_contract.py \
  tests/test_effort_promotion_authority.py \
  tests/test_effort_main_output_contract.py
python -m coverage report -m
```

Execution environment: CPython 3.13.5 and pytest 9.0.2. This was a partial local checkout containing the complete production leaf, not a replacement implementation. Package initialization and the complete legacy integration suite were not run locally. The original test files retain their bytes; their pre-existing docstring gaps are not reported as repaired. No whole-repository 100%, hosted GREEN, qualifying independent approval, measured routing improvement or deployment is claimed.

## Research and residual delivery work

Typed capability follows the explicit boolean/unknown contract, not truthiness or a learned score. RFC 8259 section 3 and JSON Schema 2020-12 Validation section 6.1.1 support the type distinction. Research details and APA references remain in the three carried doctoring records. No statistical library or second validation framework is needed for this existing request-validation glue.

The promotion API is deliberately non-authorizing: labels, RMSE scalars or a release receipt cannot establish observed-data provenance, an exact learned-policy artifact, validity or deployment approval. Actual latent-quality estimation and calibration must use the released Rust/fast-mlsirm owner contract. Remaining synthetic routines and hand-authored profile defaults are separate unresolved owner work; this bounded guard does not declare the entire module heuristic-free.

Current-head hosted full tests, package quality, fuzzing, security, required model reviews and qualifying independent review remain mandatory. Ready status, if used, only permits those reviews and checks to start, not merge or production promotion. No administrator bypass or automatic merge is enabled. The large canonical product-gap baseline and remaining root-document reconciliation were not modified by this integration record and are still pending; no false baseline-update claim is made.
