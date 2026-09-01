"""Reconcile PR #1000 NIM repair-driver drift and stale routing documents."""

from __future__ import annotations

from pathlib import Path

from scripts.ci import repair_pr1000_nim_evidence_v3 as v3


_original_replace_once = v3.replace_once
ARCHITECTURE = Path("docs/architecture.md")
CONTROL_PLANE_ADR = Path("docs/adr/0002-control-plane-orchestrator.md")


def _replace_once_with_post_v1_state(
    path: Path, old: str, new: str, label: str
) -> None:
    """Accept the one documented post-v1 skip-reason rewrite, else stay strict."""
    if label != "pricing skip reason provider usage":
        _original_replace_once(path, old, new, label)
        return

    text = path.read_text(encoding="utf-8")
    if text.count(old) == 1:
        path.write_text(text.replace(old, new, 1), encoding="utf-8")
        return

    post_v1_old = old.replace(
        '"no_worker_priced_by_scenario"',
        '"no_uniquely_price_dominant_worker"',
    )
    post_v1_new = new.replace(
        '"no_worker_priced_by_scenario"',
        '"no_uniquely_price_dominant_worker"',
    )
    count = text.count(post_v1_old)
    if count != 1:
        raise RuntimeError(
            f"{label}: expected exactly one legacy or post-v1 match, found {count} post-v1"
        )
    path.write_text(text.replace(post_v1_old, post_v1_new, 1), encoding="utf-8")


def _replace_document(path: Path, old: str, new: str, label: str) -> None:
    """Replace one exact stale decision statement or fail closed on document drift."""
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def patch_research_conformance_docs() -> None:
    """Remove current-form authorization for the retired deterministic heuristic."""
    _replace_document(
        ARCHITECTURE,
        """The deliberate simplification is the policy. The paper systems learn routing and topology from rewards; this lab uses a deterministic capability-hint heuristic only for worker/role routing so the repo runs without training data, GPUs, or vendor credentials. It is never an answer-quality, verification, or accept/reject judgment: verifier decisions must use the structured model judge and fail closed (see [ADR 0001](planning/adrs/0001-fail-closed-model-judgment.md)).\n\nAdd learned routing only when there is an evaluation set and logs proving the heuristic policy is the bottleneck.\nThe [NIM cost-quality benchmark](nim_benchmark.md) is that evaluation set's supplier: it discovers the hosted catalog dynamically, probes every modality contract, and compares route/conduct/single-worker policies with paired uncertainty — evidence first, learned policy later.\n""",
        """The control plane does not substitute a deterministic routing heuristic for the learned coordinators described by Fugu, TRINITY, and Conductor. Explicit caller/operator model identity and hard capability/privacy/cost eligibility remain authoritative. When more than one eligible worker remains, automatic ordering requires complete exact-context evidence from the governed fast-mlsirm routing model; absent or incomplete evidence leaves selection unresolved and fails closed instead of falling back to priority, metadata similarity, provider/model name, discovery order, transport-composite scores, or another hand-authored tie-break. Verifier decisions likewise remain structured model judgments and fail closed (see [ADR 0001](planning/adrs/0001-fail-closed-model-judgment.md)).\n\nA learned coordinator may replace this evidence-only boundary only after an independently evaluated model identifies the routing estimand and generalization contract. The [NIM cost-quality benchmark](nim_benchmark.md) supplies measured provider/cost-quality evidence, but benchmark evidence does not itself authorize an invented deterministic routing rule. The current Sakana Fugu implementation remains a learned conductor architecture: Sakana AI's August 2026 Gemma 4 replication retrained the conductor and evaluated it on a held-out test set, reinforcing that the cited research basis is learned/evaluated orchestration rather than a hand-written heuristic.\n""",
        "architecture heuristic policy",
    )
    _replace_document(
        ARCHITECTURE,
        "- replayable evaluation runs before any learned coordinator replaces the deterministic policy.\n",
        "- replayable evaluation runs before any learned coordinator replaces the evidence-only fail-closed selection boundary.\n",
        "architecture planning heuristic reference",
    )

    _replace_document(
        CONTROL_PLANE_ADR,
        "- Status: Accepted\n",
        "- Status: Accepted; amended 2026-09-02\n",
        "ADR status",
    )
    _replace_document(
        CONTROL_PLANE_ADR,
        """4. **Deterministic policy.** Worker and role selection uses a deterministic\n   capability-hint heuristic so the lab runs without training data, GPUs, or\n   vendor credentials. The heuristic is never an answer-quality,\n   verification, or accept/reject judgment.\n""",
        """4. **Evidence-only selection.** Hard capability, privacy, cost-pool, and explicit\n   caller/operator identity constraints define eligibility. A singleton is identified\n   directly. Multiple eligible workers require complete exact-context fast-mlsirm\n   routing evidence or an explicit worker choice; absent/incomplete evidence fails\n   closed. Priority, keyword/capability-hint similarity, provider/model names,\n   discovery order, transport-composite scores, and deterministic identifier ties\n   are not routing authority.\n""",
        "ADR deterministic heuristic decision",
    )
    _replace_document(
        CONTROL_PLANE_ADR,
        """6. **Learned routing is future work.** Add a trained coordinator only when an\n   evaluation set and logs show the heuristic is the bottleneck. Until then,\n   do not invent a learned router in this repo.\n""",
        """6. **Learned routing requires validation.** A trained coordinator may replace the\n   evidence-only boundary only after an independent evaluation identifies its\n   routing estimand, generalization scope, and failure contract. Lack of a trained\n   coordinator never authorizes a deterministic heuristic fallback.\n""",
        "ADR learned-routing decision",
    )
    _replace_document(
        CONTROL_PLANE_ADR,
        """- Heuristic routing will underperform a trained coordinator on some tasks.\n- Preprint coordinators may change if a later archival version appears;\n  this ADR must be re-checked against the then-current abs page before\n  treating those papers as final.\n""",
        """- Ambiguous multi-candidate requests fail closed when complete exact-context\n  routing evidence is unavailable, reducing availability rather than inventing\n  an ordering.\n- TRINITY and Conductor were subsequently presented as ICLR 2026 research and\n  Sakana AI continues to validate learned Fugu conductors; this ADR must still\n  be re-checked when those implementations or evidence contracts change.\n""",
        "ADR heuristic consequence",
    )
    adr = CONTROL_PLANE_ADR.read_text(encoding="utf-8")
    current_evidence = """

## 2026-09-02 research-conformance amendment

The original deterministic capability-hint policy is retired. The production
boundary now follows explicit eligibility plus identified evidence, with
fail-closed ambiguity. This does **not** claim equivalence to the trained
coordinators in the cited work. It removes the contradictory fallback that the
research basis does not support.

Current source review also changes the publication context. Sakana AI describes
Fugu as grounded in the TRINITY and Conductor work presented at ICLR 2026 and
explicitly contrasts learned orchestration with hand-designed workflows. Its
2026-08-10 Gemma 4 replication retrained the conductor and evaluated it on a
held-out test set, providing newer evidence that Fugu's routing authority is a
trained/evaluated model rather than a deterministic local heuristic.

Additional current references:

Fugu Team, Sakana AI. (2026). *Sakana Fugu technical report* (arXiv:2606.21228).
https://arxiv.org/abs/2606.21228

Sakana AI. (2026, August 10). *Toward base-model-independent orchestration:
Validating a Gemma 4 version of Sakana Fugu*. https://sakana.ai/fugu-gemma4/
"""
    if current_evidence.strip() not in adr:
        CONTROL_PLANE_ADR.write_text(adr.rstrip() + current_evidence + "\n", encoding="utf-8")


def main() -> None:
    """Run strict source repair, reconcile verified drift, and align current docs."""
    v3.replace_once = _replace_once_with_post_v1_state
    v3.main()
    patch_research_conformance_docs()


if __name__ == "__main__":
    main()
