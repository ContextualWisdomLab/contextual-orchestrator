from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]


def read_text(relative_path: str) -> str:
    return (ROOT_DIR / relative_path).read_text(encoding="utf-8")


def test_product_planning_is_paper_grounded():
    planning_text = read_text("docs/product_planning.md")

    for expected_text in [
        "Sakana Fugu Technical Report",
        "TRINITY",
        "Conductor",
        "single model interface",
        "latency-quality",
        "access list",
        "provider exclusion",
        "i18n",
    ]:
        assert expected_text in planning_text


def test_screen_design_maps_papers_to_enterprise_surfaces():
    screen_text = read_text("docs/screen_design.md")

    for expected_text in [
        "Paper-to-screen Traceability",
        "Workflow Run Trace",
        "Access List Inspector",
        "Evaluation Replay",
        "Audit & Compliance",
    ]:
        assert expected_text in screen_text


def test_user_stories_keep_source_basis_and_backlog_boundaries():
    stories_text = read_text("docs/user_stories.md")

    assert "Source Basis" in stories_text
    assert "provider or model as excluded" in stories_text
    assert "verifier decisions" in stories_text
    assert "Backlog Stories" in stories_text
    assert "learned routing can replace heuristics only when it proves better" in stories_text


def test_rest_api_design_marks_planned_product_surfaces():
    api_text = read_text("docs/rest_api_design.md")

    for expected_text in [
        "/api/v1/workflow_runs/{workflow_run_id}",
        "/api/v1/evaluation_runs",
        "/api/v1/access_reports/{workflow_run_id}",
        "/api/v1/agent_pools/{agent_pool_id}/worker_agents/{worker_agent_id}",
    ]:
        assert expected_text in api_text


if __name__ == "__main__":
    test_product_planning_is_paper_grounded()
    test_screen_design_maps_papers_to_enterprise_surfaces()
    test_user_stories_keep_source_basis_and_backlog_boundaries()
    test_rest_api_design_marks_planned_product_surfaces()
    print("ok")
