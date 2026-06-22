# Workflow Context

## Method

Use TDD, DDD, and CDD together.

## TDD

Paper claims become executable contracts before implementation changes:

- Fugu report: one public interface fuses fast routing and deep workflows.
- TRINITY: explicit Thinker, Worker, and Verifier role contracts.
- Conductor: workflow steps carry access lists that control visible prior work.

Run:

```bash
python tests/test_self_check.py
python tests/test_paper_contracts.py
python tests/test_admin_contract.py
python tests/test_conventions.py
python tests/test_api_contract.py
```

## DDD

Keep domain language consistent:

- Agent: configured worker model with identity, model id, provider endpoint, tags, and priority.
- WorkflowStep: one delegated subtask with role, assigned agent, and access list.
- Orchestrator: application service that routes or conducts.
- ModelClient: infrastructure adapter for mock and OpenAI-compatible workers.

No interface or factory until a second real implementation exists.

## CDD

Context lives under `conductor/`. Update it when scope, dependencies, workflow, or domain terms change.
