from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.main import app
from data_gate.gate import get_gate
from modules.activity.engine import build_activity_dashboard
from modules.ai_assist.engine import build_client_message_draft, build_rm_brief
from modules.goal_decision.engine import decide_for_goal
from modules.portfolio.engine import PortfolioDraftStore, calculate_portfolio_analytics, portfolio_universe, validate_weights


def test_workspace_context_is_client_scoped():
    gate = get_gate()
    first, second = gate.client_views()[:2]
    left = calculate_portfolio_analytics(first.client.client_id, goal_id=first.goals[0].goal_id, gate=gate)
    right = calculate_portfolio_analytics(second.client.client_id, goal_id=second.goals[0].goal_id, gate=gate)
    assert left["context"]["clientId"] == first.client.client_id
    assert right["context"]["clientId"] == second.client.client_id
    assert left["context"]["clientSnapshotId"] != right["context"]["clientSnapshotId"]
    assert left["calculation_id"] != right["calculation_id"]


def test_weight_input_uses_basis_points_and_residual_cash():
    result = validate_weights([
        {"asset_id": "A", "weight_bps": 2_550},
        {"asset_id": "B", "weight_bps": 7_000},
    ])
    assert result["total_weight_bps"] == 9_550
    assert result["residual_cash_bps"] == 450
    assert result["save_allowed"] is True


def test_over_100_percent_is_blocked():
    with pytest.raises(ValueError, match="TOTAL_WEIGHT_EXCEEDS_100_PERCENT"):
        validate_weights([
            {"asset_id": "A", "weight_bps": 6_000},
            {"asset_id": "B", "weight_bps": 4_001},
        ])


def test_current_and_draft_are_separate_and_draft_persists(tmp_path: Path):
    gate = get_gate()
    view = gate.client_views()[0]
    analytics = calculate_portfolio_analytics(view.client.client_id, gate=gate)
    weights = [{"asset_id": row["asset_id"], "weight_bps": row["weight_bps"]} for row in analytics["weights"] if row["asset_id"] != "CASH:THB"]
    before = [(holding.symbol, holding.market_value) for holding in view.client.holdings]
    store = PortfolioDraftStore(tmp_path / "drafts.json")
    draft = store.save(view.client.client_id, f"portfolio_{view.client.client_id}", weights)
    reloaded = PortfolioDraftStore(tmp_path / "drafts.json").get(draft["draft_id"])
    after = [(holding.symbol, holding.market_value) for holding in gate.client_view(view.client.client_id).client.holdings]
    assert reloaded == draft
    assert before == after
    assert draft["current_portfolio_mutated"] is False
    assert draft["auto_trade"] is False


def test_unconfirmed_goal_requires_clarification():
    gate = get_gate()
    view = next(view for view in gate.client_views() if any(not goal.confirmed_with_client for goal in view.goals))
    goal = next(goal for goal in view.goals if not goal.confirmed_with_client)
    result = decide_for_goal(view.client.client_id, goal.goal_id, {"planned_contribution": 0}, gate=gate)
    assert result["status"] == "NEED_GOAL_CLARIFICATION"
    assert result["alternatives"] == []
    assert any(q["field"] == "client_confirmed" for q in result["clarification_questions"])


def test_goal_decision_has_pareto_options_without_opaque_score():
    gate = get_gate()
    view = next(view for view in gate.client_views() if any(goal.confirmed_with_client for goal in view.goals))
    goal = next(goal for goal in view.goals if goal.confirmed_with_client)
    result = decide_for_goal(
        view.client.client_id,
        goal.goal_id,
        {"client_confirmed": True, "planned_contribution": 0},
        gate=gate,
    )
    assert result["status"] in {"READY", "BLOCKED"}
    assert "KEEP_CASH" in {row["alternative_id"] for row in result["alternatives"]}
    assert "PORTFOLIO_ADJUSTMENT" in {row["alternative_id"] for row in result["alternatives"]}
    assert result["human_decision_required"] is True
    assert result["auto_send"] is False
    assert result["auto_trade"] is False
    assert all("score" not in row for row in result["alternatives"])
    assert result["calculation_id"].startswith("CAL-GOAL-")


def test_dashboard_cards_all_deep_link_and_old_routes_are_frontend_redirects():
    response = TestClient(app).get("/api/dashboard")
    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]["clients"] == 300
    assert payload["summary"]["review_today"] == 48
    assert payload["summary"]["care"] == 37
    assert payload["summary"]["growth"] == 11
    assert len(payload["top_attention"]) == 5
    assert len(payload["daily_review_candidates"]) == 48
    assert all(card["href"].startswith("/") for card in payload["cards"])
    assert len(payload["active_clients"]) == payload["summary"]["clients"]
    assert payload["activity"]["by_investment_activity"]["active_trading"] >= 1
    assert payload["activity"]["by_investment_activity"]["holding_only"] >= 1
    opportunities = payload["ai_product_opportunities"]
    assert opportunities["items"]
    assert any(item["product_candidates"] for item in opportunities["items"])
    assert opportunities["auto_send"] is False
    assert opportunities["auto_trade"] is False


def test_activity_keeps_transaction_and_relationship_status_separate():
    activity = build_activity_dashboard(gate=get_gate())
    row = activity["rows"][0]
    assert {"last_deposit_on", "last_withdrawal_on", "last_trade_on"} <= row.keys()
    assert row["investment_activity"] in {
        "active_trading", "active_cash_flow", "holding_only", "no_recent_investment_activity",
    }
    assert row["relationship_activity"] in {"recent_contact", "contact_cooling", "contact_silent"}
    assert row["permitted_action"] in {
        "DO_NOT_CONTACT", "CHECK_CONTACT_LOCK", "CONFIRM_DATA",
        "REVIEW_BEFORE_REENGAGE", "REVIEW_NEXT_NEED",
    }


def test_product_detail_keeps_missing_contract_fields_explicit():
    response = TestClient(app).get("/api/products/P001")
    assert response.status_code == 200
    product = response.json()["product"]
    assert product["fees"] == "MISSING"
    assert product["factsheet"] == "NOT_SUPPORTED_BY_CURRENT_CONTRACT"


def test_v24_canonical_analytics_and_goal_decision_routes():
    client = TestClient(app)
    analytics = client.get("/api/clients/C1001/portfolio/analytics?goal_id=GC1001-1")
    decision = client.get("/api/goal-decisions?client_id=C1001&goal_id=GC1001-1")
    assert analytics.status_code == 200
    assert analytics.json()["context"]["clientId"] == "C1001"
    assert decision.status_code == 200
    assert decision.json()["goal_id"] == "GC1001-1"


def test_ai_brief_uses_validated_numbers_and_cannot_send_or_trade():
    brief = build_rm_brief("C1001", "GC1001-1", gate=get_gate())
    evidence = brief["numeric_evidence"][0]
    required = {
        "value", "unit", "asOf", "sourceRefs", "formulaId", "calculationId",
        "modelVersion", "assumptionVersion", "inputHash", "reasonCodes",
    }
    assert required <= evidence.keys()
    assert brief["mode"] == "GOVERNED_AI_TEMPLATE_FALLBACK"
    assert brief["live_llm_connected"] is False
    assert brief["human_review_required"] is True
    assert brief["auto_send"] is False
    assert brief["auto_trade"] is False
    assert "RM ตรวจ" in brief["draft_message"]


def test_portfolio_universe_separates_live_market_identity_from_demo_bank_policy():
    result = portfolio_universe(get_gate(), limit=250)
    providers = {item["provider"] for item in result["items"]}
    assert "SETSMART" in providers
    assert "BANK_PRODUCT_CATALOG" in providers
    market_item = next(item for item in result["items"] if item["provider"] == "SETSMART")
    assert market_item["approved_shelf_state"] == "REQUIRES_BANK_SHELF_CHECK"
    assert market_item["eligible_for_draft"] is True
    assert "approved" not in result["source_boundary"]["SETSMART"].lower()


def test_calculation_charts_metrics_and_model_allocations_share_one_result():
    result = calculate_portfolio_analytics("C1001", goal_id="GC1001-1", gate=get_gate())
    assert result["metrics"]["observation_count"] == len(result["chart_data"]["wealth"]) == 60
    assert result["metrics"]["max_drawdown"] == abs(min(row["value"] for row in result["chart_data"]["drawdown"]))
    assert result["metrics"]["scenario_cvar95_empirical"] >= result["metrics"]["scenario_var95_empirical"]
    assert result["chart_data"]["scenario_kind"] == "DETERMINISTIC_MODEL_SCENARIO"
    assert "historical" not in result["method"].lower()
    assert result["display_calculation_id"].startswith("CAL-")
    for model in result["model_allocations"]:
        assert sum(row["weight_bps"] for row in model["weights"]) <= 10_000
        assert max(row["weight_bps"] for row in model["weights"]) <= 3_500


def test_panic_line_draft_is_reviewable_and_never_sent_automatically():
    draft = build_client_message_draft("C1001", "PANIC_MARKET_DROP", "GC1001-1", gate=get_gate())
    assert draft["channel"] == "LINE"
    assert draft["status"] == "DRAFT_REQUIRES_RM_REVIEW"
    assert draft["human_review_required"] is True
    assert draft["rm_can_edit"] is True
    assert draft["auto_send"] is False
    assert draft["auto_trade"] is False
    assert draft["line_connector"] == "NOT_CONFIGURED"
    assert all(word not in draft["draft_message"] for word in ["รับประกัน", "รีบขาย"])
    assert {"known", "unknown", "next_action"} <= draft["information_design"].keys()
