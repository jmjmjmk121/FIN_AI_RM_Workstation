"""FastAPI service exposing the four modules to the frontend.

The browser never talks to SETSMART. It talks to this service, which reads the
key server-side and returns only data. No endpoint returns credential material.
"""

from __future__ import annotations

from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from data_gate.gate import get_gate
from data_gate.models import ActivityStatus, GoalType, KycStatus, Lane
from modules.activity.engine import build_activity_dashboard
from modules.ai_assist.engine import build_book_product_opportunities, build_client_message_draft, build_rm_brief
from modules.attention.engine import build_attention_list, build_daily_review_queue, summarise
from modules.kyc.engine import build_kyc_dashboard
from modules.goal_decision.engine import decide_for_goal
from modules.portfolio.engine import (
    calculate_portfolio_analytics,
    client_workspace_context,
    get_draft_store,
    portfolio_universe,
    portfolio_snapshot,
)
from modules.recommendation.engine import load_catalog, recommend

app = FastAPI(
    title="RM AI Workstation",
    description="Attention & Channel, Product Recommendation, Activity and KYC modules.",
    version="0.1.0",
)

# The Vite dev server runs on a different origin during development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict:
    """Configuration and provider status. Never includes the API key."""
    return get_gate().health()


@app.get("/api/clients")
def clients(rm_id: Optional[str] = None) -> dict:
    gate = get_gate()
    views = gate.client_views(rm_id or gate.settings.rm_id)
    attention_by_client = {
        row.client_id: row.to_dict() for row in build_attention_list(rm_id=rm_id, gate=gate)
    }
    activity_by_client = {
        row["client_id"]: row for row in build_activity_dashboard(rm_id=rm_id, gate=gate)["rows"]
    }
    return {
        "as_of": gate.as_of.isoformat(),
        "clients": [
            {
                "client_id": v.client.client_id,
                "name": v.client.name,
                "segment": v.client.segment,
                "risk_profile": v.client.risk_profile.value,
                "mandate": v.client.mandate.value,
                "aum": v.client.aum,
                "investable_cash": round(v.client.investable_cash, 2),
                "kyc_status": v.kyc.kyc_status.value if v.kyc else "missing",
                "activity_status": activity_by_client.get(v.client.client_id, {}).get("status", "unknown"),
                "last_activity_on": activity_by_client.get(v.client.client_id, {}).get("last_activity_on"),
                "why_now": attention_by_client.get(v.client.client_id, {}).get("headline_th", "ยังไม่มีเหตุเร่งด่วน"),
                "next_action": attention_by_client.get(v.client.client_id, {}).get("next_best_action_th", "ทบทวนตามรอบ"),
                "lane": attention_by_client.get(v.client.client_id, {}).get("lane", "monitor"),
                "priority_evidence": attention_by_client.get(v.client.client_id, {}).get("signals", []),
                "goals": [
                    {
                        "goal_id": g.goal_id,
                        "goal_type": g.goal_type.value,
                        "label": g.label,
                        "target_amount": g.target_amount,
                        "target_date": g.target_date.isoformat(),
                        "funded_ratio": round(g.funded_ratio, 3),
                        "confirmed": g.confirmed_with_client,
                    }
                    for g in v.goals
                ],
            }
            for v in views
        ],
    }


@app.get("/api/clients/{client_id}")
def client_detail(client_id: str) -> dict:
    gate = get_gate()
    view = gate.client_view(client_id)
    if view is None:
        raise HTTPException(status_code=404, detail=f"unknown client: {client_id}")
    prices = gate.price_map()
    attention = next((i.to_dict() for i in build_attention_list(gate=gate) if i.client_id == client_id), None)
    activity_row = next((r for r in build_activity_dashboard(gate=gate)["rows"] if r["client_id"] == client_id), None)
    context = client_workspace_context(view, gate)
    return {
        "as_of": gate.as_of.isoformat(),
        "context": context,
        "client": {
            **view.client.model_dump(mode="json"),
            "investable_cash": round(view.client.investable_cash, 2),
            "liquidity_gap": round(view.client.liquidity_gap, 2),
        },
        "goals": [
            {**g.model_dump(mode="json"), "funded_ratio": round(g.funded_ratio, 6)}
            for g in view.goals
        ],
        "kyc": view.kyc.model_dump(mode="json") if view.kyc else None,
        "permission": view.permission.model_dump(mode="json") if view.permission else None,
        "attention": attention,
        "activity": activity_row,
        "data_sources": {
            "market_data": gate.eod_prices().source.upper(),
            "calculation": "LIVE_DETERMINISTIC_ENGINE",
            "client_data": "SYNTHETIC_CLIENT_360",
            "kyc_crm": "SYNTHETIC_WORKFLOW_EMULATOR",
            "bank_product_data": "DEMO_CATALOG_AND_POLICY",
            "live_bank_systems": "NOT_CONNECTED",
        },
        "holdings_market": [
            {
                "symbol": h.symbol,
                "market_value": h.market_value,
                "close": prices[h.symbol].close if h.symbol in prices else None,
                "change_pct": (
                    round(prices[h.symbol].change_pct, 2)
                    if h.symbol in prices and prices[h.symbol].change_pct is not None
                    else None
                ),
                "source": prices[h.symbol].source if h.symbol in prices else None,
            }
            for h in view.client.holdings
        ],
    }


@app.get("/api/clients/{client_id}/goals")
def client_goals(client_id: str) -> dict:
    gate = get_gate()
    view = gate.client_view(client_id)
    if view is None:
        raise HTTPException(status_code=404, detail=f"unknown client: {client_id}")
    return {
        "client_id": client_id,
        "as_of": gate.as_of.isoformat(),
        "goals": [
            {
                **goal.model_dump(mode="json"),
                "funded_ratio": round(goal.funded_ratio, 6),
                "goal_contract_status": "CONFIRMED" if goal.confirmed_with_client else "NEEDS_CONFIRMATION",
            }
            for goal in view.goals
        ],
    }


@app.get("/api/clients/{client_id}/ai-brief")
def client_ai_brief(client_id: str, goal_id: Optional[str] = None) -> dict:
    try:
        return build_rm_brief(client_id, goal_id=goal_id, gate=get_gate())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


class MessageDraftRequest(BaseModel):
    situation: str = "PANIC_MARKET_DROP"
    goal_id: Optional[str] = None


@app.post("/api/clients/{client_id}/message-drafts")
def client_message_draft(client_id: str, request: MessageDraftRequest) -> dict:
    try:
        return build_client_message_draft(
            client_id,
            situation=request.situation,
            goal_id=request.goal_id,
            gate=get_gate(),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/clients/{client_id}/portfolio")
def client_portfolio(client_id: str) -> dict:
    gate = get_gate()
    view = gate.client_view(client_id)
    if view is None:
        raise HTTPException(status_code=404, detail=f"unknown client: {client_id}")
    return portfolio_snapshot(view, gate)


@app.get("/api/portfolio-universe")
def get_portfolio_universe(
    query: str = "",
    asset_class: Optional[str] = None,
    limit: int = Query(120, ge=1, le=250),
) -> dict:
    return portfolio_universe(get_gate(), query=query, asset_class=asset_class, limit=limit)


@app.get("/api/clients/{client_id}/portfolio-analytics")
def client_portfolio_analytics(client_id: str, goal_id: Optional[str] = None) -> dict:
    try:
        return calculate_portfolio_analytics(client_id, goal_id=goal_id, gate=get_gate())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/clients/{client_id}/portfolio/analytics")
def client_portfolio_analytics_v24(client_id: str, goal_id: Optional[str] = None) -> dict:
    """v24 canonical route; the hyphenated route remains for compatibility."""
    return client_portfolio_analytics(client_id, goal_id)


class PortfolioHoldingInput(BaseModel):
    asset_id: str
    weight_bps: int = Field(ge=0, le=10_000)


class PortfolioAnalyticsRequest(BaseModel):
    client_id: str
    goal_id: Optional[str] = None
    holdings: list[PortfolioHoldingInput]


@app.post("/api/portfolio-analytics")
def portfolio_analytics(request: PortfolioAnalyticsRequest) -> dict:
    try:
        return calculate_portfolio_analytics(
            request.client_id,
            weights=[row.model_dump() for row in request.holdings],
            goal_id=request.goal_id,
            gate=get_gate(),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


class PortfolioDraftRequest(PortfolioAnalyticsRequest):
    draft_id: Optional[str] = None
    portfolio_id: Optional[str] = None
    calculation_id: Optional[str] = None


@app.get("/api/portfolio-drafts")
def portfolio_drafts(client_id: str) -> dict:
    return {"client_id": client_id, "drafts": get_draft_store().list(client_id)}


@app.post("/api/portfolio-drafts")
def save_portfolio_draft(request: PortfolioDraftRequest) -> dict:
    gate = get_gate()
    view = gate.client_view(request.client_id)
    if view is None:
        raise HTTPException(status_code=404, detail=f"unknown client: {request.client_id}")
    try:
        analytics = calculate_portfolio_analytics(
            request.client_id,
            weights=[row.model_dump() for row in request.holdings],
            goal_id=request.goal_id,
            gate=gate,
        )
        draft = get_draft_store().save(
            request.client_id,
            request.portfolio_id or f"portfolio_{request.client_id}",
            [row.model_dump() for row in request.holdings],
            draft_id=request.draft_id,
            calculation_id=request.calculation_id or analytics["calculation_id"],
        )
        return {"draft": draft, "analytics": analytics}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _assert_path_client(client_id: str, request_client_id: str) -> None:
    if client_id != request_client_id:
        raise HTTPException(status_code=409, detail="CLIENT_CONTEXT_MISMATCH")


@app.post("/api/clients/{client_id}/portfolio-drafts")
def save_client_portfolio_draft(client_id: str, request: PortfolioDraftRequest) -> dict:
    _assert_path_client(client_id, request.client_id)
    return save_portfolio_draft(request)


@app.patch("/api/clients/{client_id}/portfolio-drafts/{draft_id}")
def update_client_portfolio_draft(client_id: str, draft_id: str, request: PortfolioDraftRequest) -> dict:
    _assert_path_client(client_id, request.client_id)
    request.draft_id = draft_id
    return save_portfolio_draft(request)


@app.post("/api/clients/{client_id}/portfolio-drafts/{draft_id}/calculate")
def calculate_client_portfolio_draft(client_id: str, draft_id: str) -> dict:
    draft = get_draft_store().get(draft_id)
    if draft is None or draft.get("client_id") != client_id:
        raise HTTPException(status_code=404, detail=f"unknown draft for client: {draft_id}")
    return calculate_portfolio_analytics(client_id, weights=draft["holdings"], gate=get_gate())


@app.post("/api/clients/{client_id}/portfolio-drafts/{draft_id}/save")
def confirm_client_portfolio_draft_save(client_id: str, draft_id: str) -> dict:
    draft = get_draft_store().get(draft_id)
    if draft is None or draft.get("client_id") != client_id:
        raise HTTPException(status_code=404, detail=f"unknown draft for client: {draft_id}")
    return {
        "draft": draft,
        "state": "DRAFT_PROPOSAL_SAVED",
        "current_portfolio_mutated": False,
        "human_approval_required": True,
        "auto_trade": False,
    }


@app.get("/api/portfolio-drafts/{draft_id}")
def portfolio_draft(draft_id: str) -> dict:
    draft = get_draft_store().get(draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail=f"unknown draft: {draft_id}")
    return {"draft": draft}


# ---- Module 1 -------------------------------------------------------------


@app.get("/api/attention")
def attention(
    rm_id: Optional[str] = None,
    lane: Optional[Lane] = None,
    limit: Optional[int] = Query(None, ge=1, le=500),
) -> dict:
    gate = get_gate()
    items = build_attention_list(rm_id=rm_id, lane=lane, limit=limit, gate=gate)
    # Summarise the whole book, not just the filtered slice.
    everything = build_attention_list(rm_id=rm_id, gate=gate)
    return {
        "as_of": gate.as_of.isoformat(),
        "summary": summarise(everything),
        "items": [i.to_dict() for i in items],
    }


# ---- Module 2 -------------------------------------------------------------


@app.get("/api/products")
def products(client_id: Optional[str] = None, goal_id: Optional[str] = None) -> dict:
    gate = get_gate()
    return {
        "client_id": client_id,
        "goal_id": goal_id,
        "source": "DEMO_PRODUCT_CATALOG",
        "as_of": gate.as_of.isoformat(),
        "products": [
            {
                "product_id": p.product_id,
                "name": p.name,
                "product_type": p.product_type,
                "risk_level": p.risk_level.value,
                "goals_addressed": [g.value for g in p.goals_addressed],
                "min_investment": p.min_investment,
                "liquidity_days": p.liquidity_days,
                "horizon_years": p.horizon_years,
                "indicative_return_pct": p.indicative_return_pct,
                "description": p.description,
                "features": p.features,
                "source": "DEMO_PRODUCT_CATALOG",
                "approved_shelf_state": "DEMO_APPROVED_SHELF",
            }
            for p in load_catalog(gate)
        ]
    }


@app.get("/api/products/{product_id}")
def product_detail(product_id: str) -> dict:
    gate = get_gate()
    record = next((p for p in gate.products() if p.product_id == product_id), None)
    if record is None:
        raise HTTPException(status_code=404, detail=f"unknown product: {product_id}")
    return {
        "product": {
            **record.model_dump(mode="json"),
            "fees": "MISSING",
            "factsheet": "NOT_SUPPORTED_BY_CURRENT_CONTRACT",
            "payoff_terms": "NOT_SUPPORTED_BY_CURRENT_CONTRACT",
        },
        "source": record.source,
        "as_of": gate.as_of.isoformat(),
    }


class GoalDecisionRequest(BaseModel):
    client_id: str
    goal_id: str
    goal_contract: Optional[dict] = None


@app.get("/api/goal-decisions")
def get_goal_decisions(client_id: str, goal_id: str) -> dict:
    try:
        return decide_for_goal(client_id=client_id, goal_id=goal_id, gate=get_gate())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/goal-decisions")
def goal_decisions(request: GoalDecisionRequest) -> dict:
    try:
        return decide_for_goal(
            client_id=request.client_id,
            goal_id=request.goal_id,
            goal_contract=request.goal_contract,
            gate=get_gate(),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/goal-decisions/evaluate")
def evaluate_goal_decisions(request: GoalDecisionRequest) -> dict:
    return goal_decisions(request)


@app.get("/api/recommendations")
def recommendations(
    client_id: str,
    goals: Optional[list[GoalType]] = Query(None),
    horizon_years: Optional[float] = Query(None, ge=0, le=40),
    limit: int = Query(5, ge=1, le=20),
) -> dict:
    try:
        return recommend(
            client_id=client_id,
            goals=list(goals) if goals else None,
            horizon_years=horizon_years,
            limit=limit,
            gate=get_gate(),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# ---- Module 3 -------------------------------------------------------------


@app.get("/api/activity")
def activity(rm_id: Optional[str] = None, status: Optional[ActivityStatus] = None) -> dict:
    return build_activity_dashboard(rm_id=rm_id, status=status, gate=get_gate())


# ---- Module 4 -------------------------------------------------------------


@app.get("/api/kyc")
def kyc(rm_id: Optional[str] = None, status: Optional[KycStatus] = None) -> dict:
    return build_kyc_dashboard(rm_id=rm_id, status=status, gate=get_gate())


@app.get("/api/dashboard")
def dashboard(rm_id: Optional[str] = None) -> dict:
    gate = get_gate()
    attention_rows = build_attention_list(rm_id=rm_id, gate=gate)
    backlog_summary = summarise(attention_rows)
    daily_review_rows = build_daily_review_queue(
        attention_rows,
        limit=gate.settings.rm_daily_review_limit,
        care_limit=gate.settings.rm_daily_care_review_limit,
    )
    daily_review_summary = summarise(daily_review_rows)
    attention_data = [row.to_dict() for row in daily_review_rows]
    activity_data = build_activity_dashboard(rm_id=rm_id, gate=gate)
    kyc_data = build_kyc_dashboard(rm_id=rm_id, gate=gate)
    product_opportunities = build_book_product_opportunities(rm_id=rm_id, gate=gate)
    market_result = gate.eod_prices()
    views = gate.client_views(rm_id or gate.settings.rm_id)
    view_by_client = {view.client.client_id: view for view in views}
    attention_by_client = {row["client_id"]: row for row in attention_data}
    active_clients = []
    for row in activity_data["rows"]:
        view = view_by_client[row["client_id"]]
        attention = attention_by_client.get(row["client_id"], {})
        confirmed_goals = [goal for goal in view.goals if goal.confirmed_with_client]
        primary_goal = sorted(
            confirmed_goals or view.goals,
            key=lambda goal: (goal.priority, goal.target_date),
        )[0] if view.goals else None
        active_clients.append({
            **row,
            "kyc_status": view.kyc.kyc_status.value if view.kyc else "missing",
            "lane": attention.get("lane", "monitor"),
            "why_now": attention.get("headline_th") or row.get("reengagement_reason") or "ติดตามตามรอบ",
            "next_action": attention.get("next_best_action_th") or "ทบทวน Goal และ activity ล่าสุด",
            "primary_goal": (
                {
                    "goal_id": primary_goal.goal_id,
                    "label": primary_goal.label,
                    "confirmed": primary_goal.confirmed_with_client,
                }
                if primary_goal else None
            ),
        })
    investment = activity_data["summary"]["by_investment_activity"]
    return {
        "as_of": gate.as_of.isoformat(),
        "summary": {
            "clients": len(views),
            "review_today": daily_review_summary["total"],
            "care": daily_review_summary["care"],
            "growth": daily_review_summary["growth"],
            "blocked": daily_review_summary["blocked"],
            "attention_backlog": backlog_summary["total"],
            "care_backlog": backlog_summary["care"],
            "growth_backlog": backlog_summary["growth"],
            "top_visible": min(gate.settings.rm_top_attention_limit, daily_review_summary["total"]),
            "inactive_or_dormant": activity_data["summary"]["at_risk"],
            "kyc_blocked": kyc_data["summary"]["advice_blocked"],
        },
        "cards": [
            {
                "id": "all-clients",
                "title": "ลูกค้าทั้งหมด",
                "value": len(views),
                "detail": "พอร์ตลูกค้าที่ RM รับผิดชอบ",
                "href": "/dashboard?activity=all",
            },
            {
                "id": "review-today",
                "title": "คัดมาทบทวนวันนี้",
                "value": daily_review_summary["total"],
                "detail": f"Care {daily_review_summary['care']} · Growth {daily_review_summary['growth']} · แสดง Top {min(gate.settings.rm_top_attention_limit, daily_review_summary['total'])}",
                "href": "/dashboard?activity=review_today",
            },
            {
                "id": "active-trading",
                "title": "Active Trading",
                "value": investment["active_trading"],
                "detail": "มีรายการซื้อขายใน 6 เดือน",
                "href": "/dashboard?activity=active_trading",
            },
            {
                "id": "active-cash-flow",
                "title": "Active Cash Flow",
                "value": investment["active_cash_flow"],
                "detail": "มีฝากหรือถอนใน 6 เดือน",
                "href": "/dashboard?activity=active_cash_flow",
            },
            {
                "id": "holding-only",
                "title": "Holding Only",
                "value": investment["holding_only"],
                "detail": "ยังถือสินทรัพย์ แม้ไม่มีรายการล่าสุด",
                "href": "/dashboard?activity=holding_only",
            },
            {
                "id": "at-risk",
                "title": "Dormant / Inactive",
                "value": activity_data["summary"]["at_risk"],
                "detail": "ต้องตรวจ ownership และ gate ก่อน re-engage",
                "href": "/dashboard?activity=at_risk",
            },
        ],
        "top_attention": attention_data[: gate.settings.rm_top_attention_limit],
        "daily_review_candidates": attention_data,
        "review_policy": {
            "kind": "DEMO_DAILY_SCREENING_CAPACITY",
            "limit": gate.settings.rm_daily_review_limit,
            "care_allocation": gate.settings.rm_daily_care_review_limit,
            "top_visible": gate.settings.rm_top_attention_limit,
            "note_th": "เป็นชุดเคสให้ RM ทบทวน ไม่ใช่เป้าหมายให้ติดต่อลูกค้าทุกราย",
        },
        "active_clients": active_clients,
        "ai_product_opportunities": product_opportunities,
        "activity": activity_data["summary"],
        "kyc": kyc_data["summary"],
        "data_sources": {
            "market_data": market_result.source.upper(),
            "market_as_of": market_result.as_of.isoformat() if market_result.as_of else None,
            "market_degraded_reason": market_result.degraded_reason,
            "client_data": "SYNTHETIC_CLIENT_360",
            "calculation": "LIVE_DETERMINISTIC_ENGINE",
        },
    }


# ---- Market ---------------------------------------------------------------


@app.get("/api/market/eod")
def market_eod(security_type: str = "All", limit: int = Query(50, ge=1, le=200)) -> dict:
    gate = get_gate()
    result = gate.eod_prices(security_type)
    return {
        "meta": result.meta(),
        "rows": [r.model_dump(mode="json") for r in result.rows[:limit]],
    }
