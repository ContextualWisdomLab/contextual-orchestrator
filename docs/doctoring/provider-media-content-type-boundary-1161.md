# Provider media content-type boundary

Issue #1161 concerns the provider-to-browser media boundary at the shared
`_send_bytes()` writer. Approved audio/video types and ordinary file formats
remain unchanged. Active markup types such as `text/html` and SVG, malformed
values containing header controls, and unknown types become
`application/octet-stream`.

The boundary is covered by authenticated HTTP tests for speech output. File,
video, transcription, and batch-download paths use the same writer.
