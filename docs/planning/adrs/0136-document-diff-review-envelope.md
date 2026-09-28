---
id: "0136"
title: "Binary document diff review through an extracted-object envelope"
status: proposed
proposed_date: "2026-09-22"
deciders:
  - "repository maintainer"
affected_components:
  - "contextual_orchestrator/document_diff_review.py"
  - "contextual_orchestrator/server.py"
related:
  - path: "docs/doctoring/document_diff_review.md"
    relation: runbook
---

# Binary document diff review through an extracted-object envelope

## Context

GitHub shows no patch for DOCX, HWPX, PDF, or image changes. Noema's verdict
gate requires changed-line evidence, so a binary-only research-document PR
cannot receive a substantive review. Sending either binary to a remote model
would also move original documents, participant material, or credentials to a
third party.

## Decision

The review leaf (`ContextualWisdomLab/.github`) materializes the base and head
blobs on its own runner, extracts page/object records, and diffs them by
locator. It sends `POST /v1/document_diff_reviews` a
`document_diff_review.v1` envelope: `repo`, `path`, `base_blob`, `head_blob`,
`extractor_version`, a `participant_material: false` attestation, and objects
with `page`, `object_kind`, `locator`, `change`, per-side `sha256:` hashes, and
bounded per-side text. Figures and blob-level `page` objects carry hashes and
caption text only, never pixels. An optional `zdr_only` boolean defaults to
`true`: document reviews use only zero-data-retention routes unless the caller
explicitly opts out (for example, a public repository). Without an eligible
route the request fails closed before any provider call.

The gateway validates the envelope before any provider call and rejects:
unknown fields; inline binary or media (file signatures, `data:` URIs, long
base64 runs); credential shapes; resident registration numbers;
participant-data paths or a missing attestation; and hash/change
inconsistencies. It asks the free pool for structured findings. Each model
finding must name an envelope object and quote at least one span of that
object's text or a named related object's text, and nothing else. Otherwise the response is `502
unsupported_evidence`. Deterministic rule findings (figure image changed,
caption unchanged) do not depend on a model.

Base/head alignment is a sequence diff over extracted objects, as in Myers'
O(ND) difference algorithm (Myers, 1986, https://doi.org/10.1007/BF01840446),
applied to layout-aware document objects rather than lines, following the
text-plus-layout document representation of LayoutLM (Xu et al., 2020,
https://doi.org/10.1145/3394486.3403172). Neither paper is redistributed
here; both are cited for design lineage only.

## Consequences

- The provider sees extracted text and hashes only. The test fixture proves
  that neither DOCX nor its base64 form appears in any provider payload.
- `base_blob`/`head_blob` are format-checked but unverifiable by the gateway.
- Participant detection is attestation plus heuristics, not proof of absence.
- Pixel-level figure review waits for multimodal free-route selection
  (contextual-orchestrator #1203) and a per-object opt-in in a later contract
  version.
