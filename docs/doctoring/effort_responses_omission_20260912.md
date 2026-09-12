# Omit native effort on both request surfaces

Status: Proposed; PR #1136, not a protected-main release.
Date: 2026-09-12.
Owner: ContextualWisdomLab/contextual-orchestrator request-profile boundary.

## Exact failure and causal owner

Independent review comment `3995701675` on PR #1136 identified a valid second omission path at head `b4343b2241ca25cb6b39dc68f98065f3e4103395`. `apply_request_profile` removed Chat Completions `reasoning_effort` but retained Responses `reasoning.effort`. The real `ModelClient.apply_effort_profile(..., api_surface="responses")` only converts a present top-level effort key after this helper returns. An incoming nested effort therefore survived the explicit unsupported-provider `omit` policy.

The actual adapter was inspected at `contextual_orchestrator/orchestrator.py`, blob `0481829dc23ed831148f5c290bf27fafb0860ff5`. This is not an assumed consumer behavior or a mock-only complaint. No evidence attributes a particular live provider incident to this fault.

## Repair and alternatives

Under explicit `omit` with unproven support, remove both native effort spellings. For a dictionary containing nested effort, first copy its independent options, then remove only `effort`. Keep the remaining dictionary, including `summary` and `mode`; remove the `reasoning` container only when that effort removal leaves it empty. Do not mutate a dictionary shared by the caller or another request.

Rejected alternatives: retaining stale effort; deleting the entire reasoning configuration including unrelated options; mutating the aliased nested dictionary; declaring success only from the leaf test without checking the real adapter. No inference call, learned score, arbitrary limit, new fallback, token allocation or capability guess is introduced.

The helper does not validate or reinterpret every arbitrary `reasoning` value: the repair acts only on a dictionary containing the effort field. False/unknown capability with `abstain` or `error` still rejects before mutation. Malformed capability still rejects before mutation. No-profile passthrough remains unchanged. Supported-effort translation elsewhere in ModelClient is not modified or claimed repaired by this slice.

## Test and delivery identities

- Test-first commit: `7246d1d31e10e363fafb3309ef0756eba026ce41`.
- Production commit: `25d2ed2261e4932b44716be56ed93f6bc55be2bf`.
- Complete production blob: `a29e4b450b2104a71940cd9e91b975b2d5d8695f`.
- New test blob: `049c62d677d3d0205a26e8d495e20fb7cffc2b2b` (`tests/test_effort_responses_omission.py`).

The new module has nineteen collected cases. Fifteen exercise the complete actual production leaf. Four instantiate the real `ModelClient` and `ModelAgent` and call the Responses adapter without making a provider request. The integration cases use `https://provider.invalid/v1` so they cannot acquire mock-agent automatic capability support.

Against the original complete source blob `2698a4c3e7f82070d865e96406c4071e4e068c50`, the fifteen local cases produced **4 failed / 11 passed**: the expected nested effort remained. With the repair, all previous focused cases plus the fifteen new leaf cases produced **104 passed**, warnings treated as errors. Four real-client integration cases were not run in the partial local checkout; they remain ordinary collected tests in the full hosted suite, with no skip/xfail in their source.

The complete local source and new test were matched to the exact pushed Git blobs above and the 104-case run was repeated. The changed helper covers **27/27 executable statements and 18/18 branch arcs**. Whole-module coverage is **76%**, not 100%. Commands for reproducing the explicitly scoped local check:

```sh
python -m coverage run --branch --source=contextual_orchestrator -m pytest -q -W error \
  tests/test_effort_capability_evidence.py \
  tests/test_effort_omission_contract.py \
  tests/test_effort_promotion_authority.py \
  tests/test_effort_main_output_contract.py \
  tests/test_effort_responses_omission.py -k 'not real_client'
python -m coverage report -m
```

The complete CI suite must run the real-client cases as well. This local scope is not a change to or replacement for the mandatory full suite.

## Historical hosted proof is not new-head proof

Before this review repair, run `34684203774`, job `103528199132` tested merge commit `cfa2657044fd335df3e51e6dd06344a6dc8ead8f`: **3690 passed / 2 skipped**, followed by successful wheel build, install and import. The GitHub merge commit and PR head `b4343b2241ca25cb6b39dc68f98065f3e4103395` have the identical tree `9fa14103a1423b6da9de1063d8fe25f55a575c8f`, verified from Git data. This is valid historical base/head integration evidence, but it does not prove the new source commit or real-client regressions pass. Fresh current-head required CI and independent review remain necessary. The original #1119 and #1000 remain open; there is no protected merge, immutable release or consumer adoption claim.

## Standards and research boundary

The Responses request schema distinguishes effort from other reasoning options. OpenAI's reasoning guide documents nested effort and summary together and describes mode separately. Those definitions justify preserving the independent fields; they do not prescribe a chosen effort, mode, budget or routing policy. Native parameter validation remains distinct from latent-quality measurement. The existing Fugu/TRINITY/Conductor and Rust/fast-mlsirm authority boundaries in the carried research records remain unchanged.

### References

OpenAI. (n.d.). *Reasoning models: Reasoning summaries and modes* [Developer documentation]. Retrieved September 12, 2026, from https://developers.openai.com/api/docs/guides/reasoning

Bray, T. (Ed.). (2017). *The JavaScript Object Notation (JSON) data interchange format* (RFC 8259). RFC Editor. https://www.rfc-editor.org/rfc/rfc8259.html
