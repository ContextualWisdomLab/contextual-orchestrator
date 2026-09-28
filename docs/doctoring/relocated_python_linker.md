# Relocated Python library path in the Rust gate

Hosted run 36328655329, Rust job 108646220452, source
1af61fc0c02504205d9f3d8161a3dac4e43eeb50, completed with exit 101.
Pinned Python setup and Clippy passed. The workspace test executable failed
at link time, before running tests: `unable to find library -lpython3.12`.
The log records the runtime library path under the runner's `_work/_tool`
directory but the linker's search argument under `/opt/hostedtoolcache`.
Selecting the interpreter in #1309 fixed discovery but did not correct this
relocated build-time library directory.

The Rust job now checks for the configured interpreter's actual shared
library at `sys.base_prefix/lib/LDLIBRARY` and supplies that directory as
`RUSTFLAGS=-L native=...` to both Clippy and workspace tests. Missing libraries
stop before compilation. Crate features, locked versions and test scope are
unchanged. This is CI bootstrap configuration, not application credential
configuration.

Verification: repository metadata tests 17 passed; actionlint and diff check
exit 0. A matching-head hosted terminal pass remains required; local linker
probes do not establish the whole Rust workspace gate or release acceptance.
