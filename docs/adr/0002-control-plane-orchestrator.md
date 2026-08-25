# ADR 0002: Control-plane orchestrator, not a trained coordinator

- Status: Accepted
- Date: 2026-08-25
- Decision owners: ContextualWisdomLab
- Series: `docs/adr` only. This is not planning ADR 0002
  (`docs/planning/adrs/0002-explicit-local-mlx-evaluation.md`).

## Context

The public shape of this lab is one OpenAI-compatible model API. Behind that
API, a pool of workers plus an orchestrator decide when to answer on a single
worker (`route`) and when to run a multi-step workflow (`conduct`).

Three published research systems describe a similar *public* shape and are
already recorded in `docs/architecture.md`:

- **TRINITY** uses a compact trained coordinator that, on each turn, selects
  an LLM and assigns one of three roles: Thinker, Worker, or Verifier
  (Xu et al., 2025).
- **Conductor** trains a coordinator with reinforcement learning to emit
  natural-language workflow steps, each with an assigned worker and an access
  list of prior step outputs (Nielsen et al., 2025).
- **Sakana Fugu** presents a production orchestration product as one model
  API that selects a worker for latency or generates a deeper workflow for
  quality, over a swappable agent pool (Sakana AI, 2026a, 2026b).

Those systems learn routing and topology. This repository is a control-plane
lab. Cloning a trained coordinator would require training data, GPUs, and a
claim of equivalence that the product does not make.

Xu et al. (2025) and Nielsen et al. (2025) are arXiv **preprints**. They are
not treated as final journal or conference versions. Sakana Fugu sources are
cited only because the launch page and technical-report PDF still resolve.

## Decision

This repository implements the **public one-API control-plane shape**, not a
trained Fugu, TRINITY, or Conductor clone.

1. **Public model.** `contextual-orchestrator` is the orchestration candidate.
   Configured `ModelAgent` records are worker candidates. Discovery does not
   administratively disable the public model.
2. **Two paths.** `route` selects one worker for simple or latency-sensitive
   work. `conduct` builds a workflow of `thinker → worker → verifier →
   synthesizer` steps.
3. **Access lists.** Each `WorkflowStep` carries an access list so a worker
   sees only the prior outputs deliberately exposed to it (Conductor-style
   visibility, implemented as data on the step, not as a trained topology
   policy).
4. **Deterministic policy.** Worker and role selection uses a deterministic
   capability-hint heuristic so the lab runs without training data, GPUs, or
   vendor credentials. The heuristic is never an answer-quality,
   verification, or accept/reject judgment.
5. **Judgment stays fail-closed.** Verifier accept/reject uses the structured
   model judge and fails closed. That product decision lives in planning
   ADR 0001 (`docs/planning/adrs/0001-fail-closed-model-judgment.md`) and is
   not restated as a new product rule here.
6. **Learned routing is future work.** Add a trained coordinator only when an
   evaluation set and logs show the heuristic is the bottleneck. Until then,
   do not invent a learned router in this repo.

## Consequences

### Positive

- Callers keep one compatible API while operators can inspect route versus
  conduct, roles, and access lists.
- The lab stays runnable offline with `mock://` agents.
- Paper claims stay attached to public shape, not to a false claim of
  trained-coordinator equivalence.

### Negative

- Heuristic routing will underperform a trained coordinator on some tasks.
- Preprint coordinators may change if a later archival version appears;
  this ADR must be re-checked against the then-current abs page before
  treating those papers as final.

### Neutral

- TRINITY's three roles plus this lab's synthesizer step are an explicit
  control-plane extension, not a hidden fourth trained role.

## References

Nielsen, S., Cetin, E., Schwendeman, P., Sun, Q., Xu, J., & Tang, Y. (2025).
*Learning to orchestrate agents in natural language with the Conductor*
[Preprint]. arXiv. https://doi.org/10.48550/arXiv.2512.04388

Sakana AI. (2026a, June 22). *Sakana Fugu: One model to command them all*.
https://sakana.ai/fugu-release/

Sakana AI. (2026b). *Fugu technical report* [Technical report].
https://github.com/SakanaAI/fugu/blob/main/Fugu_technical_report.pdf

Xu, J., Sun, Q., Schwendeman, P., Nielsen, S., Cetin, E., & Tang, Y. (2025).
*Trinity: An evolved LLM coordinator* [Preprint]. arXiv.
https://doi.org/10.48550/arXiv.2512.04695
