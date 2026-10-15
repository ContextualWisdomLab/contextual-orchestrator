# Central workflow contract migration: source preparation

The active workflow is unchanged. This test-only preparation keeps local
execution checks working while adding an immutable central-fixture reader for
a future thin caller. It does not activate self-hosted execution.

The fixture is inert comparison data fetched at an exact supplier commit. Its
Git blob identity was independently checked against GitHub. The manifest binds
its SHA-256 and Git blob ID to that exact central reference. Tests perform no
network calls and never execute fixture YAML. `protected_publication_commit`
is null because the supplier remains unmerged. A caller adopting this candidate
will fail closed, even if the bytes and candidate commit otherwise match.

Before activation, obtain ordinary protected supplier publication and runner
admission/isolation/cleanup acceptance. Re-fetch the workflow at the accepted
immutable commit, verify its GitHub blob ID, update the fixture and both digests,
and record that protected commit in the manifest. Then update the thin caller
and verify its triggers, concurrency, scoped permissions and actual check names.
The manifest is a review-controlled source receipt, not independent proof of
branch protection or a substitute for live checks and approval.

Original executable-gate assertions remain intact and read the verified supplier
only when the active workflow becomes a thin caller. Caller trigger assertions
continue reading the local workflow. No quality threshold, security scanner,
runner access, secret, protection rule or deployed component is changed.

Verification: focused original workflow assertions pass with the current local
layout and a temporary simulated-published caller. Adversarial reader tests
reject unpublished suppliers, wrong pin/digest/blob identity, mutable/dynamic
references, mixed execution and tampered fixtures. The simulation is test-only;
its publication marker is never copied into this source. Full product runtime
suites and actual new-head Actions remain required.

The reader intentionally supports only the explicit, one-job thin-caller form.
Its restricted line matching is not a general YAML parser, execution-authorization
mechanism, or proof of runner isolation. Actionlint and live governance gates
remain separate requirements.
