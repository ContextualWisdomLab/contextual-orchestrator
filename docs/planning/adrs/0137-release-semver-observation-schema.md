---
id: "0137"
title: "Versioned release SemVer observation schemas: observations only, fast-mlsirm receipt forwarded unchanged"
status: proposed
proposed_date: "2026-09-26"
deciders:
  - "repository maintainer"
affected_components:
  - "contextual_orchestrator/schemas/release_semver/"
  - "pyproject.toml ([tool.setuptools.package-data])"
  - ".gitattributes"
  - "docs/release-semver-observation.md"
related:
  - path: "docs/planning/adrs/0129-canonical-immutable-release.md"
    relation: "release mechanism this contract ships inside; unchanged"
  - path: "docs/cefr-language-observation.md"
    relation: "pattern this slice is modeled on (observations, not decisions)"
success_criteria:
  - metric: "no version authority in contextual-orchestrator"
    target: "no schema field carries a release version, decision, outcome or model self-reported confidence; the fast-mlsirm receipt document is the only decision authority"
    source: "tests/test_release_semver_schema_v1.py"
  - metric: "owner evidence-pack conformance"
    target: "v1 accepts a strict subset of what .github#2260 accepts at dccacc77, including #2260's evidence fixtures unchanged and every text ref #2260 generates; each rejected #2260 input is listed as an owner decision"
    source: "tests/test_release_semver_schema_v1.py; tests/fixtures/github_2260_noema_semver/"
  - metric: "schema immutability"
    target: "v1 schema bytes are pinned by SHA-256 in MANIFEST.json and in an immutability guard test, and are LF-only with end-of-line conversion disabled"
    source: "tests/test_release_semver_schema_v1.py; .gitattributes"
  - metric: "consumer verifiability"
    target: "the schemas and MANIFEST.json ship inside the released wheel"
    source: "pyproject.toml package-data; local wheel build"
---

# ADR 0137: Versioned release SemVer observation schemas

## Status

Proposed (2026-09-26). Step 1 of 5 for
[#1083](https://github.com/ContextualWisdomLab/contextual-orchestrator/issues/1083)'s
"immutable client/schema" prerequisite. This step adds JSON Schemas, a
digest manifest, fixtures and tests only. It adds no transport code and no
version-deciding code.

Numbering: 0135 is used on several open branches
(`0135-whole-request-partitioning.md`, `0135-opencode-go-provider-discovery.md`)
and 0136 by open PR #1220 (`0136-document-diff-review-envelope.md`), so this
record takes 0137.

## Context

[ContextualWisdomLab/.github#2260](https://github.com/ContextualWisdomLab/.github/pull/2260)
centralises the release-tag and publish-package workflows. Its
[ADR-0033](https://github.com/ContextualWisdomLab/.github/blob/dccacc77cd7be310d443b126ea98aec19216c816/docs/adr/0033-noema-semver-bump.md)
(Proposed) keeps automatic Noema SemVer selection **fail-closed**:
`decide_version_with_noema` defaults to `false`, and `true` fails until

1. [fast-mlsirm#2035](https://github.com/ContextualWisdomLab/fast-mlsirm/issues/2035)
   releases a calibrated release-decision receipt (explicit statistical
   model, per-class calibration and uncertainty, an explicit `no_decision`
   outcome, immutable identities, and no model self-report or arbitrary
   threshold as authority); and
2. contextual-orchestrator releases an immutable client/schema that carries
   that receipt through `orchestrator/free` using only the gateway token,
   with no provider/model override, no paid fallback, and a null default
   model timeout.

The #2260 adoption boundary also says no consumer may copy
contextual-orchestrator or fast-mlsirm source, call a raw model endpoint,
select a provider/model/group, or add a paid fallback. #2260's production
module deliberately has no model-response verdict parser.

A repo-local "ask a model for `{bump, confidence}` and pick a version" step
in contextual-orchestrator would contradict both documents. The existing
CEFR slice ([`docs/cefr-language-observation.md`](../../cefr-language-observation.md))
already shows the shape that fits: independent raters produce bounded
*observations*, and fast-mlsirm owns the calibrated decision.

In this ADR, "what #2260 accepts" means what #2260's code at `dccacc77`
would let through: the inline pack check in `release-tag.yml` (lines
237-270) plus `noema_semver_bump.py`. That part of `release-tag.yml` sits
after the fail-closed `exit 1` (lines 210-211), so it does not run today.

## Decision

1. **Observations only.** contextual-orchestrator collects independent rater
   observations over one evidence pack. It never produces or interprets a
   release version or decision, and no field in this schema family carries
   one. The fast-mlsirm receipt `document` is opaque and may contain
   fast-mlsirm's decision; the client neither writes nor reads it. The
   observation has no `confidence`, probability, score or free-text field,
   so a model self-report cannot be mistaken for authority.
2. **Receipt forwarded unchanged; one authority.** The envelope carries the
   fast-mlsirm receipt as `{schema_id, sha256, document}`, where `sha256` is
   the RFC 8785 canonical-JSON digest of `document`. The envelope has **no
   `outcome` field of its own**. A copied outcome would be a second source
   of the decision that could contradict the receipt, so `document` is the
   only decision authority.
3. **Evidence pack: a strict subset of what #2260 accepts.**
   - `evidence.schema.json` uses #2260's nine member names:
     `previous_version`, `changelog_fragments`, `removed_public_symbols`,
     `renamed_public_symbols`, `required_arg_promotions`,
     `deprecated_alias_only`, `commit_titles`, `pr_titles` (arrays of
     strings) and `api_surface_inspected`.
   - It mirrors #2260's rule: unless `api_surface_inspected` is `true`, at
     least one removed/renamed/required-arg finding is required.
   - Every pack v1 accepts, #2260 also accepts. #2260's two evidence
     fixtures validate unchanged; they are copied byte for byte, with Git
     blob ids recorded in `PROVENANCE.json`.
   - v1 rejects some inputs #2260 accepts. They are listed under
     "Inputs #2260 accepts and v1 rejects".
   - The pack carries no identifiers of ours. The evidence source commit,
     schema digests and evidence digest live in the envelope.
   - **`previous_version`: what the rater sees.**
     - #2260 never parses or validates the pack's `previous_version`. Its
       inline check fills the value only when it is falsy (missing, `null`,
       `""`, and also `0`, `false`, `[]` or `{}`), using
       `git describe --tags --abbrev=0` minus one leading `v`, or `0.0.0`
       without a tag (`release-tag.yml:225-229`, `:246-247`). Any other
       value, string or not, is kept as-is and written back unparsed.
     - The workflow always passes that git-derived value as
       `--previous-version` (`release-tag.yml:274`). The flag overrides
       `evidence.previous_version` (`noema_semver_bump.py:110`) and is the
       only previous version forwarded to the decision (`:144`). So in
       #2260 the pack text can differ from the version used for arithmetic.
     - `parse_core_semver` (`noema_semver_bump.py:26-34`; `:28` strips
       surrounding whitespace and every leading `v`) is reached only through
       `apply_bump` (`:41`), i.e. the arithmetic on the
       `--previous-version`/git value. It is never applied to the pack
       value; at `dccacc77` `decide_release_version` is fail-closed
       (`:83-95`) and does not call it at all.
     - In v1 the raters see only the pack, so they see the pack's
       `previous_version`, which must be canonical `X.Y.Z`. The producer
       writes the git-derived value there, and step 2 rejects a mismatch
       (`previous_version_source`). The rater's input and the arithmetic
       input therefore cannot diverge.
4. **Observation (`cwl_release_semver_observation/v1`).**
   - It holds the echoed `evidence_sha256` and `assignment_ref`, plus
     `observed_class` (`major` | `minor` | `patch` | `abstain`, using #2260's
     bump-class labels), `evidence_refs`, `breaking_change_refs` and
     `reason_code`.
   - `assignment_ref` is a caller-issued random 128-bit nonce (32 lowercase
     hex digits), so it cannot carry verdict text.
   - **Citation refs come in two forms.**
     - An *index ref* is an RFC 6901 JSON Pointer fragment into the pack,
       `#/<list>/<index>` (0-based). It can cite any item, including
       multi-line fragments and symbols containing tabs, so an unusual
       character never forces a rater to abstain.
     - A *text ref* is a #2260 prefix plus the item with Python
       `str.strip()` whitespace removed. That is exactly how #2260's
       `detected_breaking_refs` builds `api:removed:`, `api:renamed:` and
       `api:required-arg:` refs (`noema_semver_bump.py:68-79`). #2260's
       recorded fixtures use `changelog:` and `api:deprecated-alias:`; v1
       adds `commit:` and `pr:`.
     - Text refs keep internal newlines, tabs and other characters. So every
       text ref #2260 generates is accepted, for example
       `api:removed:<symbol containing a tab>`. Leading or trailing
       whitespace, which #2260 never generates, is rejected. The whitespace
       class is spelled out as the exact `str.isspace()` set, not `\s`, so
       every validator agrees.
   - **`reason_code` is a closed enum** tied to #2260's detectors and
     partitioned by class:

     | Class | Allowed reasons |
     |---|---|
     | `major` | `removed_public_symbol`, `renamed_public_symbol`, `required_arg_promotion`, `other_breaking_change` |
     | `minor` | `deprecated_alias_only`, `feature_addition` |
     | `patch` | `fix_only`, `docs_or_internal_only` |
     | `abstain` | `insufficient_evidence`, `conflicting_evidence` |

     `other_breaking_change` covers breaking changes that #2260 records only
     as changelog/commit text (for example an HTTP route removal).
   - **Detector reasons must cite the matching list**, by text or index.
     `removed_public_symbol` needs an `api:removed:` or
     `#/removed_public_symbols/` breaking ref. The renamed and required-arg
     reasons work the same way, and `deprecated_alias_only` needs an
     `api:deprecated-alias:` or `#/deprecated_alias_only/` evidence ref.
   - **Breaking refs follow the class.**
     - `major` needs at least one breaking ref.
     - `minor` and `patch` must have none, and may not cite an item of
       #2260's three detector lists at all, by text or index.
     - `abstain` may cite breaking refs when the evidence conflicts.
     - Every class except `abstain` needs at least one evidence ref.
   - A gateway or transport failure is not an observation. #2260's
     `recorded_unavailable.json` (`status`/`detail`) is not representable. A
     failed call must not be recorded as `abstain`, because `abstain` is a
     rater's judgement. The client fails closed instead.
5. **Envelope (`cwl_release_semver_receipt_envelope/v1`).**
   - It holds the schema digests, the evidence digest,
     `evidence_source_commit`, `gateway_contract`
     (`contextual-orchestrator-contract-v1`), `model_pool` fixed to
     `orchestrator/free`, and producer identity.
   - Each observation carries a `served_route` whose `route` is fixed to
     `orchestrator/free`. The gateway reports the other fields; they are
     audit-only and never come from model output:
     - `agent_id` and `model` use a gateway-identifier character set
       (letters, digits and `. _ : / @ + -`). This only partly limits
       smuggling: `=`, `;`, `,` and spaces are excluded, so
       `release_version=1.0.0` pairs and sentences do not fit, but
       verdict-looking tokens such as `confidence:0.97` or `major` still
       match. Step 2 (`route_provenance`) catches them: all three fields
       must equal the gateway's route report, and `model` (with its
       `provider`) must also be in the free-pool catalogue; `agent_id` is
       checked against the route report only;
     - `provider` is a lowercase provider name (`openrouter`, `nvidia_nim`,
       and so on) with no model path or `:variant`.
   - It carries the opaque receipt, whose `schema_id` must be a URI or a
     fast-mlsirm identifier in fast-mlsirm's dotted
     (`fast-mlsirm.<name>.v<N>`) or hyphenated (`fast-mlsirm-<name>-v<N>`)
     form (see "Receipt identity format"). The pattern does not stop
     verdict-looking URIs; step-2 check 10 admits only an allowlisted
     identity and fails closed until step 4. Identical observation entries
     are rejected.
6. **Closed, bounded, portable.**
   - Every object schema sets `additionalProperties: false`.
   - Arrays, strings and identifiers have explicit maximums (see "Size
     caps, citation and coverage" for the list caps).
   - The per-document byte caps are recorded in each schema's `$comment`
     for the step 2 consumer to enforce: evidence 4 MiB, observation
     64 KiB, envelope 4 MiB.
   - Patterns do not use `\s`, `\d` or `\w`, whose meaning differs between
     ECMA-262 and Python `re`.
   - Python's `$` also matches before a final newline. So every
     end-anchored pattern is guarded by `not: {pattern: "\n"}` or by a
     fixed `maxLength`. Before this change, `"0.2.0\n"` and a digest with a
     trailing newline passed.
   - Repeated-digit SHA-256 values and commit ids (all zeros, all `f`, and
     so on) are rejected. This is **cosmetic**: it catches placeholders, not
     wrong digests. Integrity comes from the step 2 digest checks.
7. **Immutability and byte stability.**
   - `MANIFEST.json` maps each schema `$id` to the SHA-256 of its exact file
     bytes.
   - A test pins the v1 digests separately and fails if a v1 file is edited
     or deleted. Any change is a new `v2/` directory with new `$id`s.
   - **There is no backward-compatible v1.x change.** Once v1 is released,
     loosening a rejection costs the same as tightening one: a new `vN/`
     directory with new `$id`s, new `MANIFEST.json` digests, a new
     contextual-orchestrator release and a `.github` re-pin (step 5; step-2
     check `schema_digests` requires exact digest equality). Loosening keeps
     old documents valid under the new version, but it is still a new
     version. Until v1 is released, v1 files may still be edited in this PR,
     with every digest and pin recomputed.
   - `.gitattributes` sets `-text` on the schema directory and the schema
     test fixtures. Tests assert that the files contain no CR bytes and that
     `git check-attr` reports `text` unset, so the digests survive
     `core.autocrlf` clones and Windows-built wheels.
8. **Local `$ref` resolution only.** The `$id` values are identifiers, not
   retrieval locations. Consumers must resolve `$ref` (the envelope refers
   to the observation schema by `$id`) through a local registry built from
   the packaged files, with any remote-retrieval fallback disabled. Each
   schema's `$comment` says so. Integrity comes from the manifest digest and
   from the immutable release wheel that ships the files (ADR 0129 / #1229).
9. **Digests.** `evidence_sha256` is the SHA-256 of the RFC 8785 canonical
   JSON form of the evidence pack. v1 packs have only ASCII member names and
   no JSON numbers, so this equals
   `json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`
   encoded as UTF-8. Receipt documents may contain numbers and need a full
   RFC 8785 implementation.

## Inputs #2260 accepts and v1 rejects (owner decisions)

Status (review round 4, 2026-09-26): items 1-8 and 12 stay rejections in
v1; items 10 and 11 ship as designed; item 9 keeps rejecting oversized packs,
with the title caps raised (see below). Changing any of these after v1 is
released needs a new schema version (Decision 7), whether it loosens or
tightens:

1. **Unknown keys.** #2260 ignores unknown keys, including `$schema`; v1's
   pack is closed. Reason: unknown keys would reach raters without a
   contract.
2. **Omitted members.** #2260 fills a missing or empty `previous_version`
   (`release-tag.yml:246-247`) and tolerates omitted lists. It also
   tolerates an omitted `api_surface_inspected` when a finding exists. v1
   requires all nine members with explicit lists; both #2260 fixtures carry
   them. Reason: an omitted list is ambiguous between "none found" and "not
   collected".
3. **Null `pr_titles`, `changelog_fragments` and `commit_titles`.** #2260
   never checks these three. It does reject null API lists and a null
   `deprecated_alias_only` (`release-tag.yml:266-268`). v1 requires arrays.
4. **Non-boolean `api_surface_inspected`** (for example `"yes"`). #2260
   tests `is True`, so `"yes"` counts as "not inspected" and passes when a
   finding exists. v1 requires a JSON boolean.
5. **Non-string list items.** #2260 accepts any items in
   `changelog_fragments`, `commit_titles`, `pr_titles` and
   `deprecated_alias_only`: `{sha, title}` objects, numbers or `null`. Only
   the three API lists must be non-blank strings (`noema_semver_bump.py:73-79`).
   v1 requires strings in every list.
6. **Blank items outside the API lists.** #2260 checks blankness only for
   the three API lists. v1 rejects any item that `str.strip()` would empty.
7. **Non-canonical `previous_version`.** #2260 accepts any non-empty value
   (the pack value is not parsed): it only fills a falsy value
   (`release-tag.yml:246-247`) and otherwise keeps it unchanged, and the
   git-derived `--previous-version` overrides it (item 8). v1 requires a
   string in canonical `X.Y.Z` form of at most 64 characters, and rejects,
   for example, `"garbage"`, `"1.2"`, `"1.2.3-rc.1"`, `"01.0.0"`, `"   "`,
   `" 0.11.2 "`, `"v0.11.2"`, `"vv0.11.2"`, `"0.2.0\n"`, the non-strings
   `42`, `true` and `["0.11.2"]`, and a well-formed version longer than 64
   characters (for example `1111…1.0.0` with 65 characters). Each example
   was checked against the v1 evidence schema.
8. **The `--previous-version` override.** In #2260 the git-derived
   `--previous-version` overrides the pack (`noema_semver_bump.py:110`,
   `:144`; passed at `release-tag.yml:274`). v1 has no override. The raters
   see the pack value, the producer writes the git-derived value, and step 2
   rejects a mismatch (Decision 3).
9. **Oversized packs.** #2260 has no size limits. v1 caps them (see "Size
   caps, citation and coverage" below). The `commit_titles`/`pr_titles`
   item cap is 32768, raised from 4096 in round 4 so that this repository's
   untagged first release keeps every commit. A producer **never
   truncates**: an oversized pack fails closed with an error.
10. **v1-only citation forms.** #2260 defines no `commit:`/`pr:` prefix and
    no index refs. v1 accepts both in addition to every #2260 text ref.
11. **The reason-code set and its class mapping** are ours, tied to #2260's
    detectors. Changing them after release needs v2.
12. **Unpaired UTF-16 surrogates in strings** (for example
    `"feat: \ud800"`). #2260 accepts them: Python's `json` decodes them and
    #2260 checks only blankness. The v1 schemas accept them too (JSON Schema
    has no I-JSON keyword), but they violate I-JSON (RFC 7493), which
    RFC 8785 canonicalisation requires, and the Decision 9 digest formula
    raises `UnicodeEncodeError` on them. v1 rejects them in step 2
    (`ijson_text`).

## Size caps, citation and coverage

The Co-ordinator chose these after the second review, from realistic inputs
that the earlier draft wrongly rejected. Review round 4 (2026-09-26) kept
them, with the title caps raised:

1. **Size caps from realistic sizes.**
   - This repository has no release tag, about 2,296 commits (1,881
     non-merge, 415 merges) and 46 `CHANGELOG.d` fragments. The largest
     fragment is 7,728 characters, and two exceed 2,000. A first-release
     pack with every commit and PR title is about 270 KB. 1,705 of the
     commits landed in the 21 days from 2026-08-30 to 2026-09-19, so the
     earlier 4096-title cap could have rejected the first real pack before
     steps 2-5 land.
   - The caps are:

     | List | Max items | Max item length (characters) |
     |---|---|---|
     | `changelog_fragments` | 1024 | 16384 |
     | `commit_titles` | 32768 | 2000 |
     | `pr_titles` | 32768 | 2000 |
     | each API list and `deprecated_alias_only` | 1024 | 2000 |

   - The document caps are unchanged: 4 MiB for evidence, 64 KiB per
     observation and 4 MiB per envelope. The 4 MiB evidence cap remains the
     denial-of-service bound; 32768 titles of 106 characters are about
     3.6 MB (tested). Text refs may be up to 16405 characters (the
     longest prefix plus 16384); long items are best cited by index, and
     index refs accept up to five digits so every title position is
     citable.
   - **Selection: all commits.** `commit_titles` holds the title of every
     commit in the release range (`<previous tag>..HEAD`, or the whole
     history when there is no tag), merge commits included. It is not
     restricted to first-parent or merge subjects. `pr_titles` holds every
     pull-request title in the same range.
   - **Producers never truncate.** The producer (step 3) never truncates,
     samples or drops items to fit a cap. If a list would exceed its item
     cap, an item its length cap, or the pack the 4 MiB document cap, the
     producer fails closed before any model call, with an error that names
     the member, the cap and the observed size. A truncated list would
     bring back the "not collected versus none" ambiguity that items 2 and
     3 remove, and would silently hide evidence from the raters.
   - Blank items stay rejected.
2. **Multi-line text stays citable.**
   - Changelog fragments (25 of the 46 here are multi-line) may contain
     `\n` and `\t`, like every other item.
   - Any item can be cited by index (`#/<list>/<index>`).
   - Text refs keep internal whitespace and control characters, so every
     ref #2260 generates, including `api:removed:<symbol containing a tab>`,
     is accepted.
3. **`recorded_unavailable.json` coverage.** #2260's seventh fixture is
   copied byte for byte and recorded in `PROVENANCE.json`. Tests show it is
   not an observation, envelope or evidence pack, and that its
   `status`/`detail` cannot be attached to an `abstain` observation.

## Receipt identity format (fast-mlsirm#2035 check, 2026-09-26)

Before v1 ships, the receipt `schema_id` rule was checked against
fast-mlsirm, so that the real receipt cannot force a v2.

- [fast-mlsirm#2035](https://github.com/ContextualWisdomLab/fast-mlsirm/issues/2035)
  is an open issue (opened 2026-09-19 22:11 KST). On 2026-09-26 it had no
  comments and no linked pull request, and it publishes no receipt schema
  identity. It requires a Rust-first, versioned API/schema with
  "immutable identities for input evidence, estimator/model version,
  calibration dataset/version, parameters, generated receipt, and producing
  release", but does not fix their format.
- fast-mlsirm `main` at
  [`00f5cb91`](https://github.com/ContextualWisdomLab/fast-mlsirm/tree/00f5cb91b417e40102036eb31ab8a4b843c76076)
  uses these schema identities:
  - dotted, in the Rust core:
    [`fast-mlsirm.sampling-design.v1`](https://github.com/ContextualWisdomLab/fast-mlsirm/blob/00f5cb91b417e40102036eb31ab8a4b843c76076/crates/mlsirm-core/src/sampling_design.rs#L15),
    [`fast-mlsirm.achieved-proportion.v1`](https://github.com/ContextualWisdomLab/fast-mlsirm/blob/00f5cb91b417e40102036eb31ab8a4b843c76076/crates/mlsirm-core/src/sampling_design.rs#L21),
    [`fast-mlsirm.lineage_channel_weight_evidence.v1`](https://github.com/ContextualWisdomLab/fast-mlsirm/blob/00f5cb91b417e40102036eb31ab8a4b843c76076/crates/mlsirm-core/src/lineage_channel_weight.rs#L20-L21),
    and `fast-mlsirm.sampling-design.v2` as a
    [rejected-version test input](https://github.com/ContextualWisdomLab/fast-mlsirm/blob/00f5cb91b417e40102036eb31ab8a4b843c76076/tests/test_sampling_design.py#L175);
  - hyphenated, in the Python rubric:
    [`fast-mlsirm-item-bank-report-v2`](https://github.com/ContextualWisdomLab/fast-mlsirm/blob/00f5cb91b417e40102036eb31ab8a4b843c76076/python/fast_mlsirm/rubric/item_bank_report.py#L31);
  - one URI `$id`:
    [`https://contextualwisdomlab.github.io/fast-mlsirm/contracts/tepp-lineage-pair-criterion-posterior-v2.schema.json`](https://github.com/ContextualWisdomLab/fast-mlsirm/blob/00f5cb91b417e40102036eb31ab8a4b843c76076/contracts/tepp-lineage-pair-criterion-posterior-v2.schema.json#L3);
  - bare version strings such as `"1.0"` and `"1.1"`, which are versions,
    not identities.
- **Finding:** the earlier v1 rule accepted only URIs, so it would have
  rejected every dotted or hyphenated identity above. #2035 is Rust-first,
  and the Rust core uses the dotted form, so a receipt identity such as
  `fast-mlsirm.release-decision-receipt.v1` was the likely outcome and would
  have forced a v2.
- **Decision:** before release, v1 accepts three forms:
  - a URI, as before;
  - the dotted form `fast-mlsirm(\.<name>)+\.v<N>`, where each `<name>` is
    lowercase letters and digits joined by `-` or `_`;
  - the hyphenated form `fast-mlsirm(-<name>)+-v<N>`.

  `<N>` starts at 1. Spaces, `=`, `;`, upper case and other free text do not
  fit the fast-mlsirm forms. Bare versions such as `"1.0"` stay rejected.
  Every identity listed above is accepted (tested). If #2035 publishes an
  identity in yet another form, v1 cannot carry it and a new schema version
  is needed.
- The pattern is not the guard against verdict text; check 10 is.

## Step 2 validator cross-checks

The schemas cannot see across documents, so step 2's typed validator must
perform these checks. Fixture cases that only these checks can reject are
marked `step_2_check` in `tests/fixtures/release_semver_v1_conformance.json`,
and a test ties each mark to this list.

1. **`receipt_digest`**: `fast_mlsirm_receipt.sha256` equals the RFC 8785
   SHA-256 of `fast_mlsirm_receipt.document`.
2. **`evidence_digest`**: the envelope's `evidence_sha256` equals the
   canonical SHA-256 of the pack actually supplied, and each observation's
   `evidence_sha256` equals the envelope's.
3. **`schema_digests`**: `schema_sha256.evidence` and
   `schema_sha256.observation` equal the `MANIFEST.json` entries of the
   installed release, and those equal the file bytes.
4. **`citation_membership`**: every ref resolves to exactly one pack item.
   - An index ref must be within the list's bounds.
   - A text ref must equal `prefix + item.strip()` for an item of the list
     its prefix names.
   - An index ref and a text ref to the same item count as one citation.
5. **`class_vs_breaking_evidence`**: a `minor` or `patch` observation is
   rejected when any of the following holds:
   - #2260's independent detectors fire, that is, the pack's
     removed/renamed/required-arg lists are not empty;
   - it cites, by text or index, a changelog/commit/PR item carrying a
     breaking marker (`breaking:`, `!:`, `BREAKING CHANGE`). Today a patch
     citing `changelog:breaking: ...` passes the schema.

   The schema already rejects minor/patch citing a detector-list item
   directly.
6. **`previous_version_source`**: the pack's `previous_version` equals the
   git-derived value #2260 passes as `--previous-version`.
7. **`route_provenance`**: `served_route` agent, model and provider equal
   the gateway's route report for that call, not model output.
   - `model` is in the `orchestrator/free` catalogue for that gateway
     contract.
   - `provider` is an admitted free-pool source (`openai/...` or a `:paid`
     variant never is).
8. **`assignment_nonce`**: `assignment_ref` is the nonce issued for that
   call and is unique within the envelope.
9. **`producer_identity`**: `producer.package_version` and
   `producer.source_commit` match the installed release, and
   `evidence_source_commit` is the release commit.
10. **`receipt_schema_id`**: fail closed by allowlist.
    `fast_mlsirm_receipt.schema_id` must exactly equal an entry of
    `receipt_schema_id_allowlist` in the installed release's
    `MANIFEST.json`.
    - The allowlist ships **empty** and stays empty until step 4 adds the
      identity fast-mlsirm publishes. With an empty or malformed allowlist
      the check rejects every envelope, so a late step 4 blocks every pack
      instead of letting everything through.
    - A verdict-looking `schema_id` such as `verdict:major;confidence=0.99`
      passes the schema pattern and is not covered by `route_provenance`.
      The fixture case marked `receipt_schema_id` carries it, and tests show
      that no exact-identity allowlist admits it.
11. **`byte_caps`**: each document is within its `$comment` byte cap before
    parsing.
12. **`ijson_text`**: every string (member names and values, in the pack,
    observations and envelope) is I-JSON (RFC 7493): no unpaired UTF-16
    surrogate such as `"\ud800"`. The document is rejected before any
    digest is computed, because RFC 8785 requires I-JSON and the Decision 9
    formula raises `UnicodeEncodeError` on such a string.

**Step 2 TODO: fixture coverage.** Four of these checks have no
`step_2_check` fixture case yet: `previous_version_source`,
`producer_identity`, `byte_caps` and `ijson_text`.
Step 2 must add accept/reject cases for them together with the validator.
The test that ties fixture marks to this list only requires every mark to
name a listed check, so these entries are listed ahead of their fixtures.

## Unresolved owner decisions

None of these is decided here. The schemas neither encode nor imply an
answer, and later steps wait for the owner:

1. **0.x breaking-change rule.** Under 0.x, does a breaking change bump
   minor, or major (plain SemVer arithmetic, as #2260's `apply_bump` does
   today)? `observed_class` records the SemVer change class (`major` = a
   backward-incompatible public API change); the mapping to a bump is not
   part of this contract.
2. **First release with no tags.** The repository has no release tag while
   `pyproject.toml` declares `0.2.0`. #2260 fills `previous_version` with
   `0.0.0` when no tag exists. Is the first release decided from `0.0.0`,
   or is the declared `0.2.0` treated as the first-release candidate?
3. **Timeout policy.** ADR-0033 and the organisation require a null default
   model timeout. Is any explicit, audited timeout admissible for release
   observation, or only provider termination and user cancellation?
4. **Rater count and independence.** How many observations are required,
   and how independence is established (distinct served routes, credential
   accounts, provider families, blinding), is expected to follow from the
   fast-mlsirm#2035 estimator. The envelope allows 1 to 32 observations
   only as a bound, not as a required count.

Decided in review round 4 (2026-09-26), no longer open: the twelve inputs
#2260 accepts and v1 rejects (items 1-8 and 12 rejected, items 10 and 11
as designed, item 9 with 32768-title caps), and the size-cap, citation and
coverage defaults above.

## Planned steps (each waits on the owner and fast-mlsirm#2035)

1. This ADR, the v1 schemas, manifest, packaging and tests.
2. A typed validator that performs the step 2 cross-checks above, with no
   transport.
3. An `observe` client that sends a strict `json_schema` request to the
   provisioned `orchestrator/free` sidecar using only the gateway token
   file. No provider/model selection is exposed.
4. `verify-envelope`, once fast-mlsirm publishes its receipt schema
   identity.
5. Ship in an immutable contextual-orchestrator release; `.github` then
   pins it (owner's lane).

## Consequences

- contextual-orchestrator gains a stable, hash-pinned contract that
  `.github` and fast-mlsirm can review before any code depends on it.
- Nothing changes at runtime. `release.yml`, `release_checks_gate.sh` and
  the human version-bump path are untouched.
- A released v1 file can never be edited; mistakes are fixed with v2.
  That applies to loosening as much as tightening: there is no
  backward-compatible v1.x schema change.
- Until step 4, step-2 check `receipt_schema_id` rejects every envelope.

## Alternatives considered

- **Repo-local verdict parser with a confidence threshold.** Rejected: it
  contradicts #2260 and fast-mlsirm#2035 (model self-report as authority,
  arbitrary threshold).
- **Copying fast-mlsirm's outcome into the envelope.** Rejected: it creates
  a second, possibly contradictory decision source.
- **`{ref, text}` evidence items with our own identifiers inside the pack.**
  Rejected: #2260 is the owner's design and uses plain strings; our
  identifiers belong in the envelope.
- **Text-only citations that forbid control characters.** Rejected: they
  rejected refs #2260 itself generates and forced abstention on multi-line
  fragments. Index refs plus #2260-exact text refs cover every item.
- **Schemas inline in Python (as the CEFR slice does).** Rejected for this
  contract: consumers outside this package must verify the exact bytes, so
  standalone files with a digest manifest are more verifiable.

## Traceability and primary references

Preston-Werner, T. (2013). *Semantic Versioning 2.0.0*. https://semver.org/spec/v2.0.0.html

JSON Schema. (2022). *JSON Schema: Draft 2020-12*. https://json-schema.org/draft/2020-12

Bryan, P., Zyp, K., & Nottingham, M. (Eds.). (2013). *JavaScript Object Notation (JSON) Pointer* (RFC 6901). RFC Editor. https://www.rfc-editor.org/rfc/rfc6901

Bray, T. (Ed.). (2015). *The I-JSON Message Format* (RFC 7493). RFC Editor. https://www.rfc-editor.org/rfc/rfc7493

Rundgren, A., Jordan, B., & Erdtman, S. (2020). *JSON Canonicalization Scheme (JCS)* (RFC 8785). RFC Editor. https://www.rfc-editor.org/rfc/rfc8785

ContextualWisdomLab/.github. (2026). *ADR-0033: Noema decides semantic-version bumps for central releases* (Proposed; PR #2260 at `dccacc77`). https://github.com/ContextualWisdomLab/.github/blob/dccacc77cd7be310d443b126ea98aec19216c816/docs/adr/0033-noema-semver-bump.md
