"""One-shot exact-head repair for PR #909 ZDR model error classification."""

from __future__ import annotations

from pathlib import Path


def main() -> None:
    """Distinguish an unknown model from a configured but ZDR-ineligible model."""
    path = Path("contextual_orchestrator/cost_router.py")
    text = path.read_text(encoding="utf-8")
    old = '''        with self.orchestrator.request_policy(request.zdr_only):
            agent = self.orchestrator._requested_agent(request.model)
            if agent is None:
                text = self.orchestrator._latest_user_text(request.messages)
                agent = self.orchestrator._select_agent(
                    text,
                    "worker",
                    free_only=request.model
                    == getattr(self.orchestrator, "FREE_MODEL", object()),
                )
'''
    new = '''        with self.orchestrator.request_policy(request.zdr_only):
            try:
                agent = self.orchestrator._requested_agent(request.model)
            except ValueError as exc:
                configured_exact = any(
                    candidate.model == request.model
                    for candidate in self.orchestrator.candidates
                )
                if configured_exact:
                    raise RuntimeError(
                        "requested model is configured but not eligible for ZDR batch routing"
                    ) from exc
                raise
            if agent is None:
                text = self.orchestrator._latest_user_text(request.messages)
                agent = self.orchestrator._select_agent(
                    text,
                    "worker",
                    free_only=request.model
                    == getattr(self.orchestrator, "FREE_MODEL", object()),
                )
'''
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"expected one ZDR selection block; found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


if __name__ == "__main__":
    main()
