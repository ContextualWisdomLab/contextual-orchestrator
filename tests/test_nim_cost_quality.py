"""Contracts for offline NIM cost-quality comparisons (issue #86 post-discovery)."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from contextual_orchestrator.nim_cost_quality import (
    CostQualityContractError,
    build_pareto_frontiers,
    build_scripted_policy_runners,
    chat_eligible_model_ids,
    format_task_prompt,
    hypothetical_cost_usd,
    load_pricing_scenario,
    load_task_manifest,
    locked_evaluation_tasks,
    plan_from_discovery_models,
    render_cost_quality_markdown,
    run_offline_cost_quality,
    run_policy_cell,
    score_exact_number_match,
    score_substring_match,
    score_task_answer,
    summarize_policy_cells,
)

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "examples" / "nim_task_manifest_offline.json"
PRICING_PATH = ROOT / "examples" / "nim_pricing_scenario_offline.json"


class TestScorersAndManifest(unittest.TestCase):
    def test_exact_number_standalone_only(self) -> None:
        expected = {"number": "21"}
        self.assertEqual(score_exact_number_match(expected, "answer is 21."), 1.0)
        self.assertEqual(score_exact_number_match(expected, "210"), 0.0)
        self.assertEqual(score_exact_number_match(expected, "121"), 0.0)

    def test_substring_case_insensitive(self) -> None:
        self.assertEqual(score_substring_match({"substring": "Paris"}, "paris is capital"), 1.0)
        self.assertEqual(score_substring_match({"substring": "Paris"}, "Lyon"), 0.0)

    def test_load_manifest_and_locked_split(self) -> None:
        manifest = load_task_manifest(str(MANIFEST_PATH))
        locked = locked_evaluation_tasks(manifest)
        self.assertGreaterEqual(len(locked), 3)
        self.assertTrue(all(t["split"] == "locked" for t in locked))

    def test_manifest_rejects_leakage(self) -> None:
        payload = {
            "manifest_version": "x",
            "tasks": [
                {
                    "task_id": "leaky_task_case",
                    "split": "locked",
                    "prompt": "The answer is 7 only.",
                    "scorer": {"name": "exact_number_match", "version": "1"},
                    "expected": {"number": "7"},
                }
            ],
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            json.dump(payload, handle)
            path = handle.name
        try:
            with self.assertRaises(CostQualityContractError):
                load_task_manifest(path)
        finally:
            os.unlink(path)

    def test_manifest_rejects_duplicate_task_id(self) -> None:
        payload = {
            "manifest_version": "x",
            "tasks": [
                {
                    "task_id": "same_task_one",
                    "split": "locked",
                    "prompt": "Name a city.",
                    "scorer": {"name": "substring_match", "version": "1"},
                    "expected": {"substring": "Oslo"},
                },
                {
                    "task_id": "same_task_one",
                    "split": "locked",
                    "prompt": "Name another city.",
                    "scorer": {"name": "substring_match", "version": "1"},
                    "expected": {"substring": "Bergen"},
                },
            ],
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            json.dump(payload, handle)
            path = handle.name
        try:
            with self.assertRaises(CostQualityContractError):
                load_task_manifest(path)
        finally:
            os.unlink(path)


class TestPricingHonesty(unittest.TestCase):
    def test_missing_scenario_is_unknown(self) -> None:
        self.assertEqual(
            hypothetical_cost_usd(None, {"m": {"prompt_tokens": 10, "completion_tokens": 5}}),
            "unknown",
        )

    def test_partial_price_table_is_unknown(self) -> None:
        scenario = load_pricing_scenario(str(PRICING_PATH))
        self.assertIsNotNone(scenario)
        self.assertEqual(
            hypothetical_cost_usd(
                scenario,
                {"unpriced-model": {"prompt_tokens": 10, "completion_tokens": 5}},
            ),
            "unknown",
        )

    def test_priced_model_returns_finite_cost(self) -> None:
        scenario = load_pricing_scenario(str(PRICING_PATH))
        cost = hypothetical_cost_usd(
            scenario,
            {"mock-scripted": {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000}},
        )
        self.assertIsInstance(cost, float)
        self.assertAlmostEqual(float(cost), 0.8, places=6)

    def test_rejects_non_finite_rate(self) -> None:
        payload = {
            "scenario_version": "bad",
            "scenario_status": "example_unreviewed",
            "usd_per_million_tokens": {"m": {"input": float("nan"), "output": 1.0}},
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            json.dump(payload, handle)
            path = handle.name
        try:
            with self.assertRaises(CostQualityContractError):
                load_pricing_scenario(path)
        finally:
            os.unlink(path)


class TestOfflineComparison(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = load_task_manifest(str(MANIFEST_PATH))
        self.tasks = locked_evaluation_tasks(self.manifest)
        self.answers = {
            "digit_sum_reasoning": {
                "direct_worker": "200",
                "route_once": "200",
                "bounded_conduct": "200",
            },
            "linear_equation_solution": {
                "direct_worker": "7",
                "route_once": "7",
                "bounded_conduct": "wrong",
            },
            "capital_recall_france": {
                "direct_worker": "Paris",
                "route_once": "Paris",
                "bounded_conduct": "Paris",
            },
            "sequence_next_fibonacci": {
                "direct_worker": "21",
                "route_once": "20",
                "bounded_conduct": "21",
            },
        }
        self.runners = build_scripted_policy_runners(self.answers, model_id="mock-scripted")
        self.pricing = load_pricing_scenario(str(PRICING_PATH))

    def test_format_task_prompt_preserves_scorable_body(self) -> None:
        task = self.tasks[0]
        formatted = format_task_prompt(task)
        self.assertIn(task["prompt"], formatted)
        self.assertIn(task["task_id"], formatted)
        # Marker must not create scorer leakage against the bare expected value path.
        scored = score_task_answer(task, formatted)
        self.assertEqual(scored["score"], 0.0)

    def test_run_offline_report_shape(self) -> None:
        report = run_offline_cost_quality(
            tasks=self.tasks,
            policy_runners=self.runners,
            model_id="mock-scripted",
            pricing_scenario=self.pricing,
        )
        self.assertEqual(report["measurement_status"], "offline_cost_quality")
        self.assertEqual(report["task_count"], len(self.tasks))
        self.assertGreaterEqual(report["cell_count"], len(self.tasks) * 3)
        self.assertTrue(all(c["actual_api_cost"] == "unknown" for c in report["cells"]))
        self.assertTrue(
            all(
                isinstance(c["hypothetical_paid_cost"], float)
                or c["hypothetical_paid_cost"] == "unknown"
                for c in report["cells"]
            )
        )
        names = {s["policy_name"] for s in report["policy_summaries"]}
        self.assertIn("route_once", names)
        self.assertIn("bounded_conduct", names)
        self.assertIn("hindsight_best_single", names)
        md = render_cost_quality_markdown(report)
        self.assertIn("offline_cost_quality", md)
        self.assertNotIn("NVIDIA_NIM_API_KEY", md)

    def test_unpriced_model_keeps_unknown_hypothetical(self) -> None:
        runners = build_scripted_policy_runners(self.answers, model_id="never-priced")
        report = run_offline_cost_quality(
            tasks=self.tasks[:1],
            policy_runners=runners,
            model_id="never-priced",
            pricing_scenario=self.pricing,
            include_hindsight_best_single=False,
        )
        self.assertTrue(all(c["hypothetical_paid_cost"] == "unknown" for c in report["cells"]))
        for summary in report["policy_summaries"]:
            self.assertEqual(summary["hypothetical_paid_cost_mean"], "unknown")

    def test_failed_runner_records_outcome(self) -> None:
        def boom(_prompt: str) -> dict:
            raise RuntimeError("provider down")

        task = self.tasks[0]
        cell = run_policy_cell(
            task=task,
            policy_name="route_once",
            runner=boom,
            model_id="mock-scripted",
            pricing_scenario=self.pricing,
        )
        self.assertEqual(cell["outcome"], "failed")
        self.assertEqual(cell["error_class"], "RuntimeError")
        self.assertEqual(cell["score"], 0.0)
        self.assertEqual(cell["actual_api_cost"], "unknown")
        self.assertEqual(cell["hypothetical_paid_cost"], "unknown")
        self.assertEqual(cell["prompt_tokens"], 0)
        self.assertEqual(cell["completion_tokens"], 0)
        self.assertEqual(cell["call_count"], 0)
        self.assertEqual(cell["usage_source"], "none")

    def test_scripted_answers_reject_non_mapping_values(self) -> None:
        from contextual_orchestrator.nim_cost_quality import validate_scripted_answers

        with self.assertRaises(CostQualityContractError):
            validate_scripted_answers({"digit_sum_reasoning": "200"})
        with self.assertRaises(CostQualityContractError):
            validate_scripted_answers({"digit_sum_reasoning": {"route_once": 7}})
        with self.assertRaises(CostQualityContractError):
            build_scripted_policy_runners({"digit_sum_reasoning": "200"})

    def test_pareto_excludes_unknown_cost(self) -> None:
        summaries = [
            {
                "policy_name": "route_once",
                "mean_score": 0.9,
                "mean_latency_ms": 10.0,
                "hypothetical_paid_cost_mean": "unknown",
            },
            {
                "policy_name": "bounded_conduct",
                "mean_score": 0.8,
                "mean_latency_ms": 20.0,
                "hypothetical_paid_cost_mean": 0.01,
            },
            {
                "policy_name": "direct_worker",
                "mean_score": 0.7,
                "mean_latency_ms": 5.0,
                "hypothetical_paid_cost_mean": 0.005,
            },
        ]
        frontiers = build_pareto_frontiers(summaries)
        cost_names = {row["policy_name"] for row in frontiers["quality_hypothetical_cost"]}
        self.assertNotIn("route_once", cost_names)
        self.assertIn("direct_worker", cost_names)

    def test_chat_eligible_filters_embeddings(self) -> None:
        ids = chat_eligible_model_ids(
            ["meta/llama-3-8b-instruct", "nvidia/nv-embedqa-e5-v5", "  "]
        )
        self.assertEqual(ids, ["meta/llama-3-8b-instruct"])

    def test_plan_from_discovery_aligns_with_dry_run(self) -> None:
        plan = plan_from_discovery_models(
            ["meta/llama-3-8b-instruct", "nvidia/nv-embedqa-e5-v5"],
            hard_request_budget=50,
        )
        self.assertEqual(plan["measurement_status"], "dry_run_plan")
        self.assertEqual(plan["admission_status"], "admitted")
        self.assertTrue(all(c["actual_api_cost"] == "unknown" for c in plan["comparison_cells"]))

    def test_summarize_empty_raises_via_offline(self) -> None:
        with self.assertRaises(CostQualityContractError):
            run_offline_cost_quality(tasks=[], policy_runners=self.runners)

    def test_summarize_policy_cells_mean(self) -> None:
        cells = [
            {
                "policy_name": "route_once",
                "score": 1.0,
                "latency_ms": 10.0,
                "hypothetical_paid_cost": 0.1,
                "outcome": "success",
            },
            {
                "policy_name": "route_once",
                "score": 0.0,
                "latency_ms": 20.0,
                "hypothetical_paid_cost": 0.3,
                "outcome": "success",
            },
        ]
        summaries = summarize_policy_cells(cells)
        self.assertEqual(len(summaries), 1)
        self.assertAlmostEqual(summaries[0]["mean_score"], 0.5)
        self.assertAlmostEqual(float(summaries[0]["hypothetical_paid_cost_mean"]), 0.2)


class TestNoSecretInModuleSurface(unittest.TestCase):
    def test_module_never_references_copilot_token(self) -> None:
        source = (ROOT / "contextual_orchestrator" / "nim_cost_quality.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("COPILOT_GITHUB_TOKEN", source)
        self.assertNotIn("os.getenv", source)
        self.assertNotIn("os.environ", source)


if __name__ == "__main__":
    unittest.main()
