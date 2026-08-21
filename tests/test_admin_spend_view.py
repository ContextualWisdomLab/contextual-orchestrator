"""Admin Spend view — spend_analytics wired into /admin/state and the console HTML.

Closes the design->code gap: the Figma Spend dashboard (node 112:212) now has a
matching operator surface backed by the real spend_analytics data.
"""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.admin import ADMIN_HTML, ADMIN_TRANSLATIONS  # noqa: E402


def test_admin_state_includes_spend_block() -> None:
    orchestrator = TaskOrchestrator([ModelAgent("general_agent", "priced-model", tags=("reasoning",))])
    orchestrator.run([{"role": "user", "content": "seed a run for spend"}])
    state = orchestrator.admin_state()

    assert "spend" in state
    spend = state["spend"]
    assert spend["measurement_status"] == "local_runtime_estimate"
    assert spend["totals"]["run_count"] == 1
    assert isinstance(spend["by_model"], list) and spend["by_model"]
    assert spend["by_model"][0]["model"] == "priced-model"


def test_admin_html_has_spend_panel_and_render() -> None:
    # The Observability view renders the spend totals + by_model table.
    assert 'id="spendTotals"' in ADMIN_HTML
    assert 'id="spendRows"' in ADMIN_HTML
    assert 'id="spendStatus"' in ADMIN_HTML
    assert 'data-i18n="spend_title"' in ADMIN_HTML
    assert "function renderSpend()" in ADMIN_HTML
    assert "renderSpend();" in ADMIN_HTML  # called from renderObservability
    assert "state.spend" in ADMIN_HTML


def test_spend_i18n_keys_present_both_locales() -> None:
    for locale in ("en", "ko"):
        for key in ("spend_title", "spend_model", "spend_output_tokens", "spend_cost", "spend_runs"):
            assert key in ADMIN_TRANSLATIONS[locale], f"{key} missing from {locale}"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
    print("ok")
