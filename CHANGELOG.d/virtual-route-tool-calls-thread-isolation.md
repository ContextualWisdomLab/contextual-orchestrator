- Kept a virtual-route caller's `tool_calls`/`finish_reason` on its own request
  thread. `ThreadingHTTPServer` serves each request on a separate thread while
  one `TaskOrchestrator` is shared, so holding the pending assistant extras as
  plain instance state let a sibling request's `_invoke` reset them between this
  thread's write and `route_once`'s read: the tool call was dropped and the
  caller received an empty assistant message with no error. Under a forced
  interleaving this lost the tool call for 24 of 48 concurrent callers; the
  extras are now thread-local and the same test observes none.
