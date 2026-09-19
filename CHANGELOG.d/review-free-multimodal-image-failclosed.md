Fixed `orchestrator/free` figure-bearing review so image_url parts require
discovery `input:image` (or legacy `vision`) free agents, admit free
text+image chat rows into the review sidecar pool, and fail closed with a
typed 400 when no image-capable free candidate remains — never a 200 that
silently ignores DOCX/HWPX figures (issue #1202). Image free admission now
composes the existing #940 `tool_call:single` request-shaped exclusion
instead of replacing general-free tool-call gating.
