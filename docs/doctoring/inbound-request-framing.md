# Inbound request framing doctoring

## Root cause

`_read_json` used `int(headers["Content-Length"])` and read that value without
handling unsupported transfer coding, duplicate fields, premature EOF, or
a read deadline. A negative value could reach an unbounded `read(-1)`.

## Implemented contract

- exactly one ASCII decimal `Content-Length` is required;
- unsupported `Transfer-Encoding` and every ambiguous combination fail closed;
- declared size is checked before reading;
- the body is read exactly and a premature EOF is rejected;
- a finite request-read timeout is applied and restored;
- framing failures close the connection and do not echo body/header content.

## Verification

```bash
pytest -q tests/test_inbound_request_framing.py
python -m compileall -q contextual_orchestrator
git diff --check
```

The implementation follows HTTP/1.1 message framing and connection-management
requirements in RFC 9112 (Fielding et al., 2022). It deliberately does not
claim support for chunked transfer coding.
