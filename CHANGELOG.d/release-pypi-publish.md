- The release workflow now publishes the verified wheel to PyPI in a new
  `publish-pypi` job that runs only after the immutable GitHub Release job
  succeeds. It uploads the exact `release-publish-inputs` wheel (no rebuild)
  after re-checking `SHA256SUMS` against the release asset and running
  `twine check --strict`, uses `pypa/gh-action-pypi-publish` v1.14.2 pinned to
  `dc37677b2e1c63e2034f94d8a5b11f265b73ba33` in the `pypi` environment with
  `contents: read` and `id-token: write`, and authenticates with the
  organization `PIPY_TOKEN` secret or, when that is empty, PyPI Trusted
  Publishing. `skip-existing: true` keeps re-runs safe; a PyPI version holding
  different files fails closed before upload, and the job ends by requiring
  PyPI's files to equal the verified manifest. See `docs/RELEASING.md`.
