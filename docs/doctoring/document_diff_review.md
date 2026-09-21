# Binary document diff review (document_diff_review.v1)

Owner split, agreed with the `.github` lead on 2026-09-22:

- `.github` (new sibling PR, not #2281): materialize base/head blobs, run the
  runner-side safety checks (size, entry count, compression ratio, macros,
  external relationships, traversal, participant and secret patterns), extract
  objects, diff them, and emit the envelope. PDFs and images are blob-level
  `page` objects with hashes.
- Gateway (this repository): `contextual_orchestrator/document_diff_review.py`
  plus the `POST /v1/document_diff_reviews` route. Contract: ADR 0136.

## Reproduce

```bash
python -m pytest tests/test_document_diff_review.py -q -W error
```

RED on `origin/main` 5665b0ad: 12 failed (route absent). GREEN on this branch:
12 passed. The fixture builds two DOCX binaries (body says 120 → 118
participants, table cell and caption still say 120, figure image replaced). A
test-side extractor derives the envelope. The response carries two located
findings. One is a rule finding (figure changed, caption unchanged) and one is
a model finding (body versus table), with quotes from the envelope. The
captured provider payloads contain no DOCX bytes, no base64 of either DOCX, no
ZIP signature, and no image bytes. Ten fail-closed cases return 4xx with no
provider call.

## Evidence boundaries

- The model finding in the test comes from a mocked provider. The test proves
  the boundary and validation, not model review quality.
- Each free-route request also triggers the existing answer-judge verification
  call. Both calls are covered by the binary-free assertion.
- `base_blob`/`head_blob` identity is not verified by the gateway.
- Participant checks are attestation, path segments, and a resident number
  pattern. They are not proof that no participant material exists.
- No figure pixels are sent in v1.
