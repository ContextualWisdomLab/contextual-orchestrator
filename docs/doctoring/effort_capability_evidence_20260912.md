# Reasoning-effort capability is typed evidence, not truthiness

Status: Proposed; main-based successor implementation on PR #1136, not a protected-main release.
Date: 2026-09-12.
Owner: ContextualWisdomLab/contextual-orchestrator, provider request-profile boundary.

## Problem and exact evidence

The exported `apply_request_profile` function treated arbitrary Python truth values as proof that a provider accepts native reasoning effort. At child head `ea0166818ea2ad7c00874b284e613199c1722ad7`, complete source blob `f876a176492d3ab51ce860bb5060a242c2f14613`, the string `"false"`, integer `1`, nonempty arrays/objects and other truthy values forwarded an explicitly configured effort even under `abstain` or `error`. A custom capability object's `__bool__` executed at this boundary. The boolean annotation did not validate runtime values.

This is a reproduced public-function defect. No evidence attributes a particular live Noema/OpenCode/Strix outage to this helper, and no provider request or credential was used in the reproduction. Current default-branch search found the helper, its public package export and tests; that search alone does not establish every downstream call site.

The unmodified complete source was reconstructed locally and matched its Git blob hash before testing. New capability cases plus the unchanged omission suite produced **48 failed / 23 passed**. The failures include admitted string/number/container values and an executed hostile truth hook, not import or syntax failures.

## Decision and alternatives

When an explicit profile is applied, `supports_reasoning_effort` accepts only literal booleans or `None`. Only `True` permits native effort. `False` and `None` preserve the configured unsupported-provider fallback: `abstain`/`error` reject before mutation; explicit `omit` removes even a previously populated effort field while preserving independently configured sampling/output fields and unrelated payload content. Other types raise `EffortProfileError` before request mutation. The diagnostic message names the field but does not render the supplied value.

Rejected alternatives are truth-value conversion, equality-to-True (which equates `1` with `True` and can run custom hooks), and interpreting string labels such as `"true"`/`"false"`. Those would create undocumented evidence coercion. Numeric thresholds, additional model calls, paid fallback or guessed capability are not substitutes. The no-profile compatibility branch remains unchanged because it does not apply a role profile or make this capability decision.

This repairs Python request-validation glue already owned by this module. It adds no numerical kernel, new dependency, classifier, router or provider probe. Ponytail's existing-code/standard-library check resolves to direct type and identity checks; a new validation framework or second policy subsystem is unnecessary.

## Traceability and scenarios

- A connector mistakenly forwards JSON string `"false"`: reject it as malformed, with no native effort or payload mutation.
- Capability evidence is unknown (`null`) and the explicit profile requires support: refuse the request-profile application; do not guess.
- Capability changes from supported to unknown and the caller explicitly chose omission: remove stale effort while retaining messages, tools, stream, model and independent controls.
- Capability is literal `true`: retain the explicit native effort and sampling/output fields; do not invent a role-based budget.
- A hostile Python object implements truth/equality/render methods: never execute those methods while validating capability evidence.

RFC 8259 distinguishes boolean, numeric, string and null JSON values. JSON Schema 2020-12 Validation section 6.1.1 matches instance types rather than coercing their values. Nullable capability is this existing helper's explicit unknown-evidence representation; the positive-only authorization rule follows the task's verified-capability contract, not a statistical estimator.

Fugu, TRINITY and Conductor describe learned selection/delegation mechanisms, not permission to infer provider support from a value's language-level truthiness. This type repair does not claim to implement their learned policies or reproduce their performance. The previously recorded model/role/native-effort separation in [learned-policy authority](learned_policy_authority_20260910.md) remains in force. `fast-mlsirm` remains the owner for empirical latent-quality estimation; capability validation is not a quality score.

## Verification and delivery boundary

RED commit: `9967a0ce1df905c203b0592bb0a39f85c47efd8c`.
Production repair: `062173a8e3fa5f375c141e0c4efafcd7f559d5dd`.
Production source blob: `8a98fd7a8be9e61595645c46a10500559deb3ac9`.

The focused command ran on the complete repaired source, with warnings treated as errors:

```sh
python -m coverage run --branch --source=contextual_orchestrator -m pytest -q -W error \
  tests/test_effort_capability_evidence.py \
  tests/test_effort_omission_contract.py \
  tests/test_effort_promotion_authority.py
python -m coverage report -m
```

Result: **83 passed**. The changed function covered **19/19 executable statements and 12/12 branch arcs**. Whole-module coverage was **75%**, not 100%. AST/docstring inspection found documentation on every definition in the changed source and new test file. No full repository test, package-import integration, hosted GREEN, release, or consumer deployment is claimed. The existing omission and authority test blobs were independently matched to `f3f99a5940764eac6d64df27cfc91e86701de6fe` and `c815feae94153e9b32637893a999b3df2b6a821d`.

At the pre-write child head, GitHub returned zero check runs and no PR-triggered workflow runs. Absence is not success. Parent #1000 integration, complete current-head CI, independent review, immutable release and consumer adoption remain required. This patch neither retires the parent nor authorizes merging its unresolved numerical/synthetic diagnostics. The large canonical product-gap baseline was read but not replaced by this bounded doctoring record; its full-tree integration is still pending.

### Main-based successor boundary repair

Review of PR #1136 at exact head `583ac7047df8129cabc3278eeb8d4ac96e43c348`
found that `ModelAgent.__post_init__` used equality-based membership for the
capability field. Python therefore admitted integer `1` and float `1.0` as
equal to `True`; a hostile object's equality hook also executed before the
request-profile boundary could apply its strict validation.

RED commit `f0ad677ceb032ad90537df47571425604a22907a` exercises the real
`ModelAgent` and `ModelClient` Responses path. It produced three intended
failures: both numeric values reached request mutation without raising, and
the hostile equality hook executed. Repair commit
`0e514f316b63fdd2c43ae345bd9d70b10c0bb25a` replaces equality with an
identity/type check at construction. The repaired production blob is
`fd9369d8309ac37624a79637fb8470af433cd30c`; malformed evidence is rejected
before normalization, rendering, fallback selection, or payload mutation.

Fresh local verification with CPython 3.12 used disabled third-party pytest
plugin autoload so an unrelated installed `pytest-asyncio` deprecation warning
could not replace repository evidence. All effort-prefixed tests plus the
client-boundary module completed with **153 passed** under `-W error`; Ruff,
`compileall`, and `git diff --check` also passed. This focused evidence does
not replace hosted exact-head Checks or independent review.

## References

Bray, T. (Ed.). (2017). *The JavaScript Object Notation (JSON) data interchange format* (RFC 8259, section 3). RFC Editor. https://www.rfc-editor.org/rfc/rfc8259.html#section-3

Wright, A., Andrews, H., & Hutton, B. (2022). *JSON Schema validation: A vocabulary for structural validation of JSON* (Draft 2020-12, section 6.1.1; Internet-Draft, not an RFC). https://json-schema.org/draft/2020-12/json-schema-validation#section-6.1.1

Sakana AI. (2026). *Sakana Fugu technical report* (arXiv:2606.21228, version 2). arXiv. https://arxiv.org/html/2606.21228v2

Xu, J., Sun, Q., Schwendeman, P., Nielsen, S., Cetin, E., & Tang, Y. (2026). *Trinity: An evolved LLM coordinator* (arXiv:2512.04695, version 3). arXiv. https://arxiv.org/html/2512.04695v3

Nielsen, S., Cetin, E., Schwendeman, P., Sun, Q., Xu, J., & Tang, Y. (2026). *Learning to orchestrate agents in natural language with the Conductor* (arXiv:2512.04388, version 5). arXiv. https://arxiv.org/html/2512.04388v5
