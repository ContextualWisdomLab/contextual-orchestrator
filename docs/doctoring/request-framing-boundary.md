# Request framing boundary

## Customer action

Send JSON requests with one non-negative decimal `Content-Length` and no
`Transfer-Encoding`. Clients that use chunked transfer encoding must route
through a front proxy that terminates and validates HTTP framing before
forwarding a length-delimited request to this stdlib gateway.

## Decision

The gateway rejects duplicate or comma-joined `Content-Length` values,
negative/signed/non-decimal values, unsupported transfer codings, bodies above
the configured byte limit, and bodies shorter than their declared length. It
closes the connection after a framing error so unread bytes cannot be parsed as
the next request. The body limit is checked before `read()`, preventing a
negative length from becoming `read(-1)` and reading until peer close.

This is deliberately narrower than implementing a chunked decoder in the
stdlib handler. A proxy may decode chunked HTTP, but the application boundary
has one framing implementation and one maximum-body policy.

## Verification

`tests/test_request_framing.py` covers absent/zero/trimmed lengths, duplicate
and comma-joined lengths, malformed and oversized values, transfer encoding,
negative-length raw sockets, chunked raw sockets, and a short declared body.

## APA 7 reference

Internet Engineering Task Force. (2022). *HTTP/1.1* (RFC 9112). RFC Editor.
https://www.rfc-editor.org/rfc/rfc9112.html
