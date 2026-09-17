- Virtual route and conduct return a worker's tool calls to the caller before
  text-answer judging or later workflow roles. Tool handoff does not create a
  text-quality observation; conduct keeps its normal workflow persistence path.
- Streamed tool calls receive missing indices without changing provider objects
  or replacing supplied indices, following the required `ChoiceDeltaToolCall.index`
  field in the [OpenAI Python SDK](https://github.com/openai/openai-python/blob/main/src/openai/types/chat/chat_completion_chunk.py).
- Progress callbacks support keyword-only output and keyword rest parameters;
  the concurrent tool-call test now fails on worker exceptions or unfinished threads.
- Validation: four reproductions failed before the repair and passed afterward;
  the additional keyword-rest callback reproduction also failed before its fix.
  The nine focused route/conduct/streaming/authorization suites passed 125 tests.
  This is local protocol evidence, not live-provider or deployed-consumer proof.
