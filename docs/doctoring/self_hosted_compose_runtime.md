# Self-hosted Compose runtime

At main `6ef802bf85b91a99ebb25e4e2d64c00763a7feaa`, Security run
36318668233 job 108618127348 finished with 5297 passes, five skips and one
failure: the real merged Compose network-boundary test returned exit 125.
The captured subprocess stderr was absent from the pytest exception display,
so the historical runner's exact plugin state is not proven.

Using an empty, task-owned Docker configuration reproduces the exact command's
exit 125: Docker reports an unknown `-f` flag when no Compose plugin is visible.
This changes no user Docker configuration and starts no container. With the
normal installed Compose 5.4.0, the four deployment-contract tests pass.

Both Security and release verification run the complete suite but previously
prepared neither Compose nor its CLI availability. Reuse the official
`docker/setup-compose-action` at commit
`54042514f505b273907334ae2b9cdbb9a0213c1a` (manifest uses Node 24), explicitly
select `v5.4.0`, and require `docker compose version` before the Python/native
build and full suite. Explicit version selection installs it even when an
unmanaged older Compose is present. The rendered network assertions remain
unchanged; a missing or unusable CLI fails before the long test run.

The workflow contract failed before the repair. All 53 focused security,
release and Compose tests pass. actionlint and diff-check exit zero. This is
local macOS proof, not a claim that the Linux self-hosted run or release passed.
No runtime image or complete toolchain-license approval follows from setup.

Primary implementation: https://github.com/docker/setup-compose-action/tree/54042514f505b273907334ae2b9cdbb9a0213c1a
