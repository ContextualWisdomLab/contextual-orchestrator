# Provider Transfer-Encoding boundary

## Decision

Contextual Orchestrator accepts only a single HTTP/1.1 `chunked` `Transfer-Encoding` on model-provider responses. Any other transfer-coding value or chain fails closed before application JSON, batch, or server-sent-event parsing begins. `Content-Length` together with any `Transfer-Encoding` remains an ambiguous-framing error under the existing response-bound contract.

This is intentionally stricter than the full HTTP/1.1 protocol. RFC 9112 permits response transfer-coding chains such as `gzip, chunked` when `chunked` is final, and also defines close-delimited behavior when a non-chunked coding is final. The repository does not implement a reviewed transfer-decoding stack for arbitrary codings. Passing such bytes through to higher-level provider parsers would therefore make application semantics depend on transport metadata that this client did not decode or validate.

Python's `http.client` is the repository's reviewed transport primitive and directly supports HTTP/1.1 chunked framing. The product consequently keeps the interoperable single `chunked` case and rejects unsupported chains instead of silently treating transfer-coded bytes as ordinary provider content.

## Security and reliability rationale

RFC 9112 makes message framing security-sensitive, identifies `Transfer-Encoding`/`Content-Length` disagreement as a potential smuggling or response-splitting signal, forbids applying `chunked` more than once, and requires recipients to understand chunked framing. A provider response can be syntactically valid HTTP while still being outside this application's decoder contract. The safe application boundary is therefore: support only the coding the selected standard-library transport decodes and fail closed on every other coding before model-output interpretation.

The cumulative 8 MiB response budget remains authoritative after chunk decoding. This change does not raise the byte limit, accept ambiguous framing, add a proxy, enable redirects, alter DNS pinning, weaken TLS hostname verification, or introduce a provider-specific exception.

## Runtime contract

`contextual_orchestrator.provider_transport._ProviderHTTPResponse` applies the following order to real `http.client.HTTPResponse` objects:

1. read `Content-Length` and `Transfer-Encoding` through the existing redacted header-inspection boundary;
2. reject the response when both fields are present;
3. when `Transfer-Encoding` is present without `Content-Length`, accept only a case-insensitive field value exactly equal to `chunked`;
4. reject empty values, alternative codings, coding chains, repeated `chunked`, or parameterized `chunked` as unsupported by the product decoder;
5. retain the existing `Content-Length` validation when no transfer coding is present; and
6. retain cumulative bounded reads, bounded SSE lines, media-type validation, terminal `[DONE]` evidence, and deterministic cleanup after framing admission.

The policy distinguishes protocol validity from product support. `gzip, chunked` can be valid HTTP/1.1 and is still rejected here because Contextual Orchestrator has no reviewed transfer-decoding layer for the preceding `gzip` coding. Compatibility must be added through a separately reviewed decoder with equivalent resource, integrity, and test coverage rather than by weakening this gate.

## Verification

Test-first commit `d3d02f33d26511707b6686edc38e5211aa490828` introduced `tests/test_provider_transfer_encoding.py` before the production gate existed. Production commit `7dc4ae62ba0f4c0e6dd2b707dae163ee01f648a2` implements the fail-closed boundary.

The regression contract covers:

- accepted `chunked` casing variants;
- rejected `gzip`;
- rejected valid-but-unsupported `gzip, chunked`;
- rejected repeated `chunked, chunked`;
- rejected parameterized `chunked;foo=bar`;
- rejected `identity` and an empty field value; and
- deterministic response and connection cleanup for every rejected coding.

Repository exact-head CI, security, coverage, review, and protected-merge gates remain authoritative. These focused tests do not substitute for the pending central coverage evidence required by PR #96.

## Operations and rollback

An upstream that emits a non-`chunked` transfer coding should be treated as incompatible with the current provider transport. Preserve the provider identity and fixed failure classification in incident evidence, then correct the upstream or introduce an explicitly reviewed decoding adapter. Do not add a one-off bypass, pass encoded bytes to model parsers, or reinterpret transport EOF as proof of a complete provider response.

If a compatibility regression is confirmed, revert this bounded transfer-coding gate as a reviewed unit while preserving the existing 8 MiB byte bound, `Content-Length` validation, ambiguous-framing rejection, DNS pinning, TLS identity, redirect rejection, proxy isolation, and response cleanup controls.

## APA 7 references

Fielding, R., Nottingham, M., & Reschke, J. (Eds.). (2022). *HTTP/1.1* (RFC 9112; STD 99). Internet Engineering Task Force. https://www.rfc-editor.org/rfc/rfc9112.html

Python Software Foundation. (2026). *http.client — HTTP protocol client*. Python 3.14.6 documentation. https://docs.python.org/3.14/library/http.client.html
