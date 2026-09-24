### Fixed

- Endpoint race observer failures now settle the manually managed `Future` exactly once instead of leaving an unbounded race in a permanent `RUNNING` state. This preserves the prior executor-backed exception semantics while retaining daemon-owned race workers that cannot block interpreter shutdown. Regression coverage exercises callback failures after both successful and failed provider attempts with `deadline_seconds=None`.
