"""One-shot exact-head repair for PR #909; deleted by its caller after validation."""

from __future__ import annotations

from pathlib import Path


def replace_exact(path: str, old: str, new: str) -> None:
    """Replace exactly one literal block or fail closed."""
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"expected exactly one replacement target in {path}; found {count}"
        )
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    """Apply the reviewed ADR and batch-model contract repairs."""
    old_adr = Path("docs/planning/adrs/0038-streamed-responses-usage-boundary.md")
    new_adr = Path("docs/planning/adrs/0040-streamed-responses-usage-boundary.md")
    if not old_adr.is_file() or new_adr.exists():
        raise SystemExit("streamed Responses ADR rename preconditions are not met")
    old_adr.rename(new_adr)

    replace_exact(
        str(new_adr),
        'id: "0038"',
        'id: "0040"',
    )
    replace_exact(
        "docs/architecture.md",
        "See [ADR 0038](planning/adrs/0038-streamed-responses-usage-boundary.md).",
        "See [ADR 0040](planning/adrs/0040-streamed-responses-usage-boundary.md).",
    )
    replace_exact(
        "CHANGELOG.md",
        "answer, and nested gateway upstreams remain compatible (ADR 0038).",
        "answer, and nested gateway upstreams remain compatible (ADR 0040).",
    )
    replace_exact(
        "contextual_orchestrator/cost_router.py",
        '''        try:
            prepared_requests = [self._resolve_batch_request(request) for request in requests]
        except (RuntimeError, ValueError) as exc:
            raise BatchModelSelectionError(
                "no eligible model-group member is available for this batch request"
            ) from exc
''',
        '''        try:
            prepared_requests = [self._resolve_batch_request(request) for request in requests]
        except ValueError:
            raise
        except RuntimeError as exc:
            raise BatchModelSelectionError(
                "no eligible model-group member is available for this batch request"
            ) from exc
''',
    )
    replace_exact(
        "contextual_orchestrator/server.py",
        '''                    job = self._run(
                        lambda: coordinator.submit_batch(
                            batch_requests,
                            metadata=metadata,
                            owner_id=security.principal_id(self.headers),
                        )
                    )
''',
        '''                    try:
                        job = self._run(
                            lambda: coordinator.submit_batch(
                                batch_requests,
                                metadata=metadata,
                                owner_id=security.principal_id(self.headers),
                            )
                        )
                    except ValueError as exc:
                        raise RequestError(400, "invalid_model", str(exc)) from exc
''',
    )

    tests = Path("tests/test_cost_review_server.py")
    test_text = tests.read_text(encoding="utf-8")
    test_name = "test_batch_routing_rejects_unknown_zdr_model_as_client_error"
    if test_name in test_text:
        raise SystemExit(f"{test_name} already exists")
    tests.write_text(
        test_text
        + '''


def test_batch_routing_rejects_unknown_zdr_model_as_client_error() -> None:
    """An unknown explicit ZDR model is a non-retryable client error."""
    server, port, token = _serve()
    try:
        status, body = _request(
            "POST",
            f"http://127.0.0.1:{port}/api/v1/batch_routing_jobs",
            token,
            {
                "model": "not-configured",
                "zdr_only": True,
                "requests": [
                    {"messages": [{"role": "user", "content": "route securely"}]}
                ],
            },
        )
    finally:
        server.shutdown()
    assert status == 400
    assert body["error"]["code"] == "invalid_model"
''',
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
