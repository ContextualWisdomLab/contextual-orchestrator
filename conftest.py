"""Pytest configuration for the repo root.

The Atheris coverage-guided harnesses under ``fuzz/`` import ``atheris`` at
module load time, which is only installed in the dedicated CI job. Ignore that
directory during normal collection so the suite runs without the native
toolchain. The Hypothesis property tests under ``tests/fuzz/`` are unaffected.

The suite also stands hundreds of throwaway ``http.server`` instances in for
provider endpoints, every one of them started as
``threading.Thread(target=server.serve_forever, daemon=True)``.
``socketserver.BaseServer.serve_forever`` only checks its stop flag once per
``poll_interval`` seconds, and ``shutdown()`` blocks until that next check, so
each teardown pays up to the 0.5s default. No call site in this repository
passes the argument, so that default is paid several hundred times per run and
dominates the wall clock: shortening it takes the suite from about eleven
minutes to about one, with no change to what is asserted.

This overrides the default rather than the call sites because a mocked server
in ``tests/test_telemetry.py`` pins production ``serve()`` to invoking
``serve_forever()`` with no arguments.
"""

import socketserver

collect_ignore = ["fuzz"]

_ORIGINAL_SERVE_FOREVER = socketserver.BaseServer.serve_forever


def _serve_forever(self, poll_interval: float = 0.01):
    """Serve with a short stop-flag poll so ``shutdown()`` returns promptly."""
    return _ORIGINAL_SERVE_FOREVER(self, poll_interval)


socketserver.BaseServer.serve_forever = _serve_forever
