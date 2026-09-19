## Fixed

- Protected-main CI now installs rustfmt and clippy for the repository-pinned Rust
  1.97.1 toolchain, follows the renamed provider embedding claim-lease constant,
  and locks anyio 4.14.2 to remove CVE-2026-63374, CVE-2026-64847, and
  CVE-2026-63349.
- Provider embedding synchronous completion now treats an explicit null wait
  timeout as unbounded, matching the default-null model timeout contract.
- The embedding shutdown regression now closes its test-owned HTTP listener
  after joining the serving thread, eliminating the strict ResourceWarning.
