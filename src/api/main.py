"""FastAPI service exposing the four modules to the frontend.

The browser never talks to SETSMART. It talks to this service, which reads the
key server-side and returns only data. No endpoint returns credential material.
"""

from __future__ import annotations

from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from data_gate.gate import get_gate
from data_gate.models import ActivityStatus, GoalType, KycStatus, Lane
from modules.activity.engine import build_activity_dashboard
from modules.attention.engine import build_attention_list, summarise
from modules.kyc.engine import build_kyc_dashboard
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
    allow_methods=["GET"],
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
                "goals": [
                    {
                        "goal_id": g.goal_id,
                        "goal_type": g.goal_type.value,
                        "label": g.label,
                        "target_amount": g.target_amount,
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
    return {
        "as_of": gate.as_of.isoformat(),
        "client": view.client.model_dump(mode="json"),
        "goals": [g.model_dump(mode="json") for g in view.goals],
        "kyc": view.kyc.model_dump(mode="json") if view.kyc else None,
        "permission": view.permission.model_dump(mode="json") if view.permission else None,
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
def products() -> dict:
    return {
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
            }
            for p in load_catalog()
        ]
    }


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


# ---- Market ---------------------------------------------------------------


@app.get("/api/market/eod")
def market_eod(security_type: str = "All", limit: int = Query(50, ge=1, le=200)) -> dict:
    gate = get_gate()
    result = gate.eod_prices(security_type)
    return {
        "meta": result.meta(),
        "rows": [r.model_dump(mode="json") for r in result.rows[:limit]],
    }
