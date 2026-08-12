# Provider JSON trust boundary

## Decision

Treat every complete document returned by a validated HTTPS model-provider request as untrusted structured data until the transport layer has bounded, decoded, and validated it. Normal provider endpoints must cross the boundary as one strict UTF-8 JSON object. OpenAI-compatible Batch API file-content responses remain JSON Lines, with every non-empty line independently required to be a strict JSON object.

The transport rejects malformed UTF-8, malformed JSON, non-finite numeric extensions (`NaN`, `Infinity`, and `-Infinity`), syntactically valid floating-point exponents that overflow Python's runtime representation to a non-finite value, duplicate object member names, and top-level non-object values. It replaces decoder failures with stable redacted `RuntimeError` messages without exception chaining. Valid objects are re-serialized before existing model-client parsing so later decoder exceptions cannot retain the original untrusted document.

This boundary supplements, rather than replaces, the existing cumulative 8 MiB provider-response byte budget and HTTP framing checks.

## Why this is a security and diligence boundary

A model-provider response can contain customer prompts, model output, tool arguments, retrieved business data, or upstream diagnostics. Python's `JSONDecodeError` exposes the parsed document through its `doc` attribute. Chaining that exception through retry or logging code can therefore turn malformed upstream content into durable diagnostic evidence containing private data.

Python also deliberately accepts several behaviors that are broader than interoperable JSON: its decoder accepts `NaN`, `Infinity`, and `-Infinity`, and repeated object names default to last-value-wins semantics. In addition, the default binary-float conversion can materialize an extreme but syntactically valid exponent such as `1e999` as infinity. Those behaviors are useful for general-purpose compatibility but are undesirable at an orchestration trust boundary because two implementations can interpret the same provider evidence differently.

RFC 8259 requires JSON exchanged between systems outside a closed ecosystem to use UTF-8, excludes literal non-finite values from the JSON number grammar, states that object names should be unique for interoperable behavior, and specifically identifies values such as `1E400` as evidence of potential interoperability problems when they exceed commonly available binary64 range and precision. The Python 3.14 documentation explicitly documents the non-finite-number extension and default repeated-name behavior, and exposes `parse_constant`, `parse_float`, and `object_pairs_hook` as controls. The implementation uses those controls to fail closed before a finite-syntax number can become a non-finite orchestration value.

## Request-path authority

The DNS-pinned HTTPS connection retains the exact request target after the final Bearer-credential check and before dispatch. The paired response wrapper uses that already-reviewed target only to distinguish response representation:

- `/files/{file_id}/content` paths are treated as Batch-compatible JSON Lines;
- every other complete validated-provider response consumed through the model client is treated as one JSON object; and
- streaming responses continue through the separate `text/event-stream` iterator boundary, where each `data:` event is now validated as a strict JSON object until `data: [DONE]`.

The request path is not a new routing authority and does not change the destination, DNS pin, TLS hostname, credentials, or provider selection. It is metadata carried from the validated outbound request to the response parser on the same connection.

## Batch compatibility

The OpenAI Batch API defines batch input and output as per-line request/output objects stored in JSONL files. Batch file-content responses therefore cannot be forced through a single-document JSON parser. The transport validates every non-empty row independently, requires an object per row, rejects duplicate names and any numeric value that would become non-finite at the Python boundary, and emits canonical UTF-8 JSON Lines for the existing batch parser.

Blank-only or malformed output fails closed. A malformed provider row is never handed to the later orchestration-level `json.loads` call, so provider-controlled text is not retained in that later exception's document field.

## Failure semantics

The boundary uses intentionally small, stable messages:

- `provider JSON response is malformed` for invalid UTF-8, invalid JSON syntax, duplicate names, non-finite extensions, float overflow to a non-finite runtime value, or parser/encoder recursion failure;
- `provider JSON response must be an object` when a valid JSON document has the wrong top-level type; and
- `provider JSON Lines response is malformed` for invalid Batch output content.

The messages do not contain provider text, parsed values, URLs with credentials, decoder offsets, or the underlying exception. Public provider retry code may wrap these stable exceptions, but the wrapped cause is already redacted and contains no original provider document.

## Resource and privacy properties

The response wrapper continues to read at most the configured cumulative response budget before parsing. Strict parsing therefore cannot turn an unbounded response into an unbounded allocation path. Canonicalization can temporarily hold the bounded parsed representation and encoded representation in memory; the byte budget remains the admission control for provider-controlled body size.

No raw provider body is added to logs, audit records, workflow traces, exception messages, or review evidence by this change. The implementation does not introduce telemetry fields, persistent state, database objects, or new credentials.

## Provider and environment boundaries

Validated production provider traffic uses HTTPS, DNS pinning, TLS hostname verification, proxy bypass, redirect rejection, and the captured request target. The plain-HTTP literal-loopback path remains an explicit integration/development seam and is not promoted to production provider authority. Lightweight response doubles without a captured validated request target retain historical byte-oriented `read()` behavior so framing and resource tests can remain isolated; focused callers can exercise `read_json_object()` directly.

Live NVIDIA NIM development continues to use the repository credential abstraction with `NVIDIA_NIM_API_KEY`. This change neither reads `COPILOT_GITHUB_TOKEN` nor changes independent reviewer credentials or identity.

## Verification

`tests/test_provider_json_boundary.py` and `tests/test_provider_json_finite_number_boundary.py` prove that:

1. malformed UTF-8 and malformed JSON are redacted and carry no original exception cause;
2. `NaN`, positive/negative infinity, duplicate names, top-level arrays, and extreme exponents that overflow to infinity are rejected;
3. valid Unicode JSON objects and ordinary finite exponent notation survive the boundary;
4. the pinned HTTPS connection records the exact provider request target;
5. chat, Responses passthrough, file-upload metadata, and batch metadata paths fail closed before their existing `json.loads` calls can retain malformed provider documents;
6. valid structured responses preserve existing caller semantics;
7. Batch output remains line-addressable JSONL after strict validation;
8. malformed Batch JSONL is redacted and resources close deterministically; and
9. explicit partial reads remain bounded byte operations and are not parsed prematurely.

Repository-local exact-head GitHub Checks remain diagnostic for the contributor head only. They do not replace trusted central 100% production statement/branch/public-docstring/package evidence, fresh required review-agent verdicts, qualifying independent approval, branch protection, or protected-main acceptance.

## Operator handling

When this boundary rejects a provider response:

1. identify the provider and endpoint from existing request/audit metadata rather than logging the response body;
2. confirm whether the upstream service returned malformed JSON, duplicate names, a non-finite extension or out-of-range exponent, an unexpected top-level type, or malformed Batch JSONL;
3. validate the provider against its current documented OpenAI-compatible contract;
4. reproduce with synthetic non-sensitive data when evidence is needed; and
5. fix the provider or compatibility adapter rather than relaxing the global parser.

A provider-specific compatibility exception requires a reviewed architectural decision and dedicated regression tests. Do not re-enable permissive Python JSON extensions globally or admit numeric values that become non-finite in the runtime representation.

## Rollback

If a conforming provider is incorrectly rejected, revert the parser change only after preserving the existing response-size, DNS-pinning, redirect, proxy, credential, TLS, and redaction protections. A rollback must not restore raw `JSONDecodeError`/`UnicodeDecodeError` propagation across the provider trust boundary. Prefer a narrowly documented provider adapter that converts a verified non-standard representation before orchestration logic consumes it.

## References

Bray, T. (2017). *The JavaScript Object Notation (JSON) Data Interchange Format* (RFC 8259). Internet Engineering Task Force. https://doi.org/10.17487/RFC8259

OpenAI. (n.d.). *Batch API reference*. Retrieved August 8, 2026, from https://platform.openai.com/docs/api-reference/batch

Python Software Foundation. (2026). *json — JSON encoder and decoder (Python 3.14.6 documentation).* https://docs.python.org/3/library/json.html
