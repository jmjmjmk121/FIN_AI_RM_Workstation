"""Deterministic client portfolio calculator and backend draft store.

The current repository has no transaction ledger or complete price history for
open-end funds. The calculator therefore exposes assumption-based diagnostics
with explicit method labels; it never calls them historical TWR/XIRR.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from calendar import monthrange
from datetime import date, datetime, timezone
from functools import lru_cache
from pathlib import Path
from threading import Lock
from typing import Optional
from uuid import uuid4

from data_gate.gate import DataGate, get_gate
from data_gate.models import ClientView, Goal

WEIGHT_BPS_TOTAL = 10_000
MAX_POSITION_BPS = 3_500
MODEL_MONTHS = 60
RISK_FREE_RATE = 0.015

# Annual arithmetic assumptions for a clearly labelled demo diagnostic.
ASSET_ASSUMPTIONS = {
    "cash": (0.015, 0.005, -0.002),
    "money_market": (0.018, 0.010, -0.006),
    "bond_fund": (0.035, 0.055, -0.080),
    "unit_trust": (0.050, 0.100, -0.160),
    "equity_etf": (0.070, 0.180, -0.280),
    "thai_equity": (0.075, 0.220, -0.350),
    "commodity_etf": (0.045, 0.200, -0.250),
    "structured_note": (0.055, 0.140, -0.300),
    "insurance": (0.020, 0.025, -0.020),
    "bond": (0.032, 0.045, -0.070),
    "other": (0.040, 0.120, -0.200),
}

SETSMART_ASSET_CLASS = {
    "CS": "thai_equity",
    "CSF": "thai_equity",
    "PS": "thai_equity",
    "PSF": "thai_equity",
    "ETF": "equity_etf",
    "UT": "unit_trust",
    "DR": "equity_etf",
    "W": "other",
    "TSR": "other",
    "DWC": "other",
    "DWP": "other",
}

ASSET_CLASS_LABELS = {
    "cash": "เงินสด",
    "money_market": "ตลาดเงิน",
    "bond_fund": "กองทุนตราสารหนี้",
    "bond": "ตราสารหนี้",
    "unit_trust": "ทรัสต์/กองทุนจดทะเบียน",
    "equity_etf": "ETF / DR",
    "thai_equity": "หุ้นไทย",
    "commodity_etf": "สินค้าโภคภัณฑ์",
    "structured_note": "Structured Product",
    "insurance": "ประกัน",
    "other": "อื่น ๆ",
}


def _hash(value: object, prefix: str) -> str:
    digest = hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()[:16]
    return f"{prefix}_{digest}"


def _assumption(asset_class: str) -> tuple[float, float, float]:
    return ASSET_ASSUMPTIONS.get(asset_class, ASSET_ASSUMPTIONS["other"])


def display_calculation_id(calculation_id: str, as_of: date) -> str:
    """Short, readable reference for RM screens; the full ID stays in Audit."""
    suffix = calculation_id.rsplit("_", 1)[-1][:8].upper()
    return f"CAL-{as_of.strftime('%Y%m%d')}-{suffix}"


def _setsmart_asset_class(security_type: str) -> str:
    return SETSMART_ASSET_CLASS.get(security_type.upper(), "other")


def portfolio_universe(
    gate: Optional[DataGate] = None,
    query: str = "",
    asset_class: Optional[str] = None,
    limit: int = 120,
) -> dict:
    """Searchable, source-labelled universe for the RM builder.

    SETSMART contributes only contract-supported identity and EOD market fields.
    Bank products remain separate demo-catalog records; being present in
    SETSMART is never treated as bank-shelf approval.
    """
    gate = gate or get_gate()
    market = gate.eod_prices()
    needle = query.strip().upper()
    items: list[dict] = []
    for row in market.rows:
        row_asset_class = _setsmart_asset_class(row.security_type)
        if asset_class and row_asset_class != asset_class:
            continue
        if needle and needle not in row.symbol.upper() and needle not in row.security_type.upper():
            continue
        items.append({
            "asset_id": f"SETSMART:{row.symbol}",
            "symbol": row.symbol,
            "name": row.symbol,
            "asset_class": row_asset_class,
            "asset_class_label": ASSET_CLASS_LABELS[row_asset_class],
            "security_type": row.security_type,
            "provider": "SETSMART",
            "source": row.source.upper(),
            "as_of": row.date.isoformat(),
            "price": row.close,
            "nav": row.nav,
            "currency": "THB",
            "return_type": "PRICE_RETURN_INPUT" if row.close is not None else "NOT_SUPPORTED",
            "approved_shelf_state": "REQUIRES_BANK_SHELF_CHECK",
            "eligible_for_draft": True,
            "data_note": "ข้อมูลตัวตนและ EOD จาก SETSMART; ไม่ได้แปลว่าธนาคารอนุมัติให้ขาย",
        })

    # Market-cap ordering keeps a large live universe usable without pretending
    # SETSMART supplies a recommendation rank.
    market_cap = {row.symbol: row.market_cap or 0.0 for row in market.rows}
    items.sort(key=lambda item: (-market_cap.get(item["symbol"], 0.0), item["symbol"]))

    product_items = []
    for product in gate.products():
        product_asset_class = {
            "mutual_fund": "unit_trust",
            "bond": "bond",
            "structured_note": "structured_note",
            "insurance": "insurance",
            "deposit": "cash",
        }.get(product.product_type, "other")
        if asset_class and product_asset_class != asset_class:
            continue
        if needle and needle not in product.product_id.upper() and needle not in product.name.upper():
            continue
        product_items.append({
            "asset_id": f"PRODUCT:{product.product_id}",
            "symbol": product.product_id,
            "name": product.name,
            "asset_class": product_asset_class,
            "asset_class_label": ASSET_CLASS_LABELS[product_asset_class],
            "security_type": product.product_type.upper(),
            "provider": "BANK_PRODUCT_CATALOG",
            "source": product.source,
            "as_of": gate.as_of.isoformat(),
            "price": None,
            "nav": None,
            "currency": product.currency,
            "return_type": "DEMO_CATALOG_ASSUMPTION",
            "approved_shelf_state": product.approved_shelf_state,
            "eligible_for_draft": True,
            "data_note": "Demo Bank Catalog & Policy; ต้องยืนยันกับ Compliance ก่อน production",
        })

    combined = items + product_items
    classes = sorted({item["asset_class"] for item in combined})
    return {
        "as_of": market.as_of.isoformat() if market.as_of else gate.as_of.isoformat(),
        "market_source": market.source.upper(),
        "market_degraded_reason": market.degraded_reason,
        "available_asset_classes": [
            {"value": value, "label": ASSET_CLASS_LABELS.get(value, value)} for value in classes
        ],
        "total_matches": len(combined),
        "items": combined[: max(1, min(limit, 250))],
        "source_boundary": {
            "SETSMART": "identity and supported EOD market fields",
            "BANK_PRODUCT_CATALOG": "demo shelf, terms and policy assumptions",
            "portfolio_numbers": "validated deterministic calculator",
        },
    }


def _years_until(on: date, target: date) -> float:
    return max(1 / 12, (target - on).days / 365.25)


def _future_value(principal: float, annual_return: float, years: float, monthly: float = 0) -> float:
    growth = principal * (1 + annual_return) ** years
    months = max(1, round(years * 12))
    monthly_rate = (1 + annual_return) ** (1 / 12) - 1 if annual_return > -1 else 0
    annuity = monthly * months if abs(monthly_rate) < 1e-12 else monthly * (((1 + monthly_rate) ** months - 1) / monthly_rate)
    return growth + annuity


def goal_outcome(goal: Goal, as_of: date, wealth: float, annual_return: float, volatility: float, monthly: float = 0) -> dict:
    years = _years_until(as_of, goal.target_date)
    base_value = _future_value(wealth, annual_return, years, monthly)
    stress_return = max(-0.95, annual_return - max(0.03, 1.65 * volatility))
    stress_value = _future_value(wealth, stress_return, years, monthly)
    shortfall = max(0.0, goal.target_amount - base_value)
    stress_shortfall = max(0.0, goal.target_amount - stress_value)
    funded_ratio = base_value / goal.target_amount if goal.target_amount > 0 else 1.0
    stress_ratio = stress_value / goal.target_amount if goal.target_amount > 0 else 1.0
    # Demo proxy, not a calibrated probability. The method is carried to UI/audit.
    success = max(0.0, min(1.0, 0.15 + 0.72 * funded_ratio - 0.35 * volatility))
    stress_success = max(0.0, min(success, 0.10 + 0.62 * stress_ratio - 0.45 * volatility))
    required_monthly = 0.0
    if shortfall > 0:
        months = max(1, round(years * 12))
        required_monthly = shortfall / months
    return {
        "goal_id": goal.goal_id,
        "goal_name": goal.label,
        "target_amount": round(goal.target_amount, 2),
        "target_date": goal.target_date.isoformat(),
        "funded_ratio": round(funded_ratio, 6),
        "success_probability": round(success, 6),
        "stress_success_probability": round(stress_success, 6),
        "expected_shortfall": round(shortfall, 2),
        "goal_shortfall_cvar": round(max(shortfall, stress_shortfall), 2),
        "required_monthly_contribution": round(required_monthly, 2),
        "method": "DEMO_DETERMINISTIC_GOAL_PROXY_V1",
    }


def client_workspace_context(view: ClientView, gate: DataGate, goal_id: Optional[str] = None, draft_id: Optional[str] = None, calculation_id: Optional[str] = None) -> dict:
    holding_fingerprint = [(h.symbol, h.units, h.market_value) for h in view.client.holdings]
    snapshot_id = _hash([view.client.client_id, gate.as_of.isoformat(), holding_fingerprint], "client")
    market = gate.eod_prices()
    market_snapshot_id = _hash([market.source, market.as_of.isoformat(), [(r.symbol, r.close) for r in market.rows]], "market")
    return {
        "clientId": view.client.client_id,
        "clientSnapshotId": snapshot_id,
        "selectedGoalId": goal_id,
        "portfolioId": f"portfolio_{view.client.client_id}",
        "draftId": draft_id,
        "marketSnapshotId": market_snapshot_id,
        "calculationId": calculation_id,
        "asOf": gate.as_of.isoformat(),
    }


def portfolio_snapshot(view: ClientView, gate: Optional[DataGate] = None) -> dict:
    gate = gate or get_gate()
    client = view.client
    invested = sum(max(0.0, h.market_value) for h in client.holdings)
    portfolio_value = invested + max(0.0, client.cash_balance)
    if portfolio_value <= 0:
        portfolio_value = max(1.0, client.aum)
    holdings = []
    for h in client.holdings:
        weight_bps = round(h.market_value / portfolio_value * WEIGHT_BPS_TOTAL)
        holdings.append({
            "asset_id": f"HOLDING:{h.symbol}",
            "symbol": h.symbol,
            "security_type": h.security_type,
            "asset_class": h.asset_class,
            "units": h.units,
            "cost_basis": round(h.cost_basis, 2),
            "market_value": round(h.market_value, 2),
            "pnl": round(h.market_value - h.cost_basis, 2),
            "weight_bps": weight_bps,
            "weight": weight_bps / WEIGHT_BPS_TOTAL,
            "position_source": "SYNTHETIC_CLIENT_360",
        })
    cash_bps = max(0, WEIGHT_BPS_TOTAL - sum(h["weight_bps"] for h in holdings))
    holdings.append({
        "asset_id": "CASH:THB",
        "symbol": "เงินสด THB",
        "security_type": "CASH",
        "asset_class": "cash",
        "units": client.cash_balance,
        "cost_basis": client.cash_balance,
        "market_value": round(client.cash_balance, 2),
        "pnl": 0.0,
        "weight_bps": cash_bps,
        "weight": cash_bps / WEIGHT_BPS_TOTAL,
        "position_source": "SYNTHETIC_CLIENT_360",
    })
    context = client_workspace_context(view, gate)
    return {
        "context": context,
        "client_id": client.client_id,
        "portfolio_id": context["portfolioId"],
        "portfolio_value": round(portfolio_value, 2),
        "benchmark": "SET TRI (reference unavailable in current SETSMART EOD contract)",
        "holdings": holdings,
        "source": {
            "positions": "SYNTHETIC_CLIENT_360",
            "market": gate.eod_prices().source.upper(),
            "as_of": gate.as_of.isoformat(),
        },
    }


def validate_weights(rows: list[dict]) -> dict:
    seen: set[str] = set()
    normalised = []
    for row in rows:
        asset_id = str(row.get("asset_id", ""))
        weight_bps = row.get("weight_bps")
        if not asset_id or asset_id in seen:
            raise ValueError("DUPLICATE_OR_MISSING_ASSET_ID")
        if not isinstance(weight_bps, int) or isinstance(weight_bps, bool) or not 0 <= weight_bps <= WEIGHT_BPS_TOTAL:
            raise ValueError("WEIGHT_BPS_INVALID")
        seen.add(asset_id)
        normalised.append({"asset_id": asset_id, "weight_bps": weight_bps})
    total = sum(row["weight_bps"] for row in normalised)
    if total > WEIGHT_BPS_TOTAL:
        raise ValueError("TOTAL_WEIGHT_EXCEEDS_100_PERCENT")
    return {
        "holdings": normalised,
        "total_weight_bps": total,
        "residual_cash_bps": WEIGHT_BPS_TOTAL - total,
        "save_allowed": total <= WEIGHT_BPS_TOTAL,
        "compare_allowed": total <= WEIGHT_BPS_TOTAL,
    }


def _asset_class_for(asset_id: str, snapshot: dict, gate: DataGate) -> str:
    existing = next((h for h in snapshot["holdings"] if h["asset_id"] == asset_id), None)
    if existing:
        return existing["asset_class"]
    if asset_id.startswith("PRODUCT:"):
        product_id = asset_id.split(":", 1)[1]
        product = next((p for p in gate.products() if p.product_id == product_id), None)
        if product:
            return {
                "mutual_fund": "unit_trust", "bond": "bond", "structured_note": "structured_note",
                "insurance": "insurance", "deposit": "cash",
            }.get(product.product_type, "other")
    if asset_id.startswith("SETSMART:"):
        symbol = asset_id.split(":", 1)[1]
        row = next((item for item in gate.eod_prices().rows if item.symbol == symbol), None)
        if row:
            return _setsmart_asset_class(row.security_type)
    return "other"


def _asset_label(asset_id: str, snapshot: dict, gate: DataGate) -> str:
    existing = next((h for h in snapshot["holdings"] if h["asset_id"] == asset_id), None)
    if existing:
        return existing["symbol"]
    if asset_id.startswith("SETSMART:"):
        return asset_id.split(":", 1)[1]
    if asset_id.startswith("PRODUCT:"):
        product_id = asset_id.split(":", 1)[1]
        product = next((p for p in gate.products() if p.product_id == product_id), None)
        return product.name if product else product_id
    return asset_id


def _correlation(left_class: str, right_class: str, same_asset: bool = False) -> float:
    if same_asset:
        return 1.0
    if "cash" in (left_class, right_class):
        return 0.05
    if left_class == right_class:
        return 0.75
    equity = {"thai_equity", "equity_etf", "unit_trust"}
    fixed_income = {"bond", "bond_fund", "money_market"}
    if {left_class, right_class} <= equity:
        return 0.65
    if (left_class in equity and right_class in fixed_income) or (right_class in equity and left_class in fixed_income):
        return 0.05
    if "commodity_etf" in (left_class, right_class):
        return 0.10
    if "structured_note" in (left_class, right_class) and (left_class in equity or right_class in equity):
        return 0.55
    return 0.25


def _portfolio_variance(weighted: list[tuple]) -> tuple[float, list[list[float]]]:
    covariance = []
    variance = 0.0
    for i, left in enumerate(weighted):
        row = []
        for j, right in enumerate(weighted):
            value = left[4] * right[4] * _correlation(left[1], right[1], i == j)
            row.append(value)
            variance += left[2] * right[2] * value
        covariance.append(row)
    return max(0.0, variance), covariance


def _month_end(as_of: date, months_back: int) -> date:
    index = as_of.year * 12 + as_of.month - 1 - months_back
    year, month_zero = divmod(index, 12)
    month = month_zero + 1
    return date(year, month, monthrange(year, month)[1])


def _scenario_asset_return(asset_id: str, asset_class: str, month_index: int) -> float:
    """Reproducible model path used only for a clearly-labelled demo scenario."""
    annual_return, annual_volatility, _ = _assumption(asset_class)
    seed = int(hashlib.sha256(asset_id.encode()).hexdigest()[:8], 16)
    phase = (seed % 628) / 100
    cycle = math.sin((month_index + 1) * 0.83 + phase)
    cycle += 0.55 * math.cos((month_index + 1) * 0.37 + phase / 2)
    shock = cycle / 1.35
    stress_by_class = {
        "thai_equity": -0.16,
        "equity_etf": -0.13,
        "unit_trust": -0.09,
        "structured_note": -0.10,
        "commodity_etf": 0.04,
        "bond": -0.025,
        "bond_fund": -0.025,
        "money_market": -0.002,
        "cash": 0.0,
    }
    stress = stress_by_class.get(asset_class, -0.06) if month_index in {14, 35, 48} else 0.0
    monthly = annual_return / 12 + annual_volatility / math.sqrt(12) * shock + stress
    return max(-0.45, min(0.35, monthly))


def _empirical_var_cvar(returns: list[float], confidence: float = 0.95) -> tuple[float, float]:
    if not returns:
        return 0.0, 0.0
    losses = sorted(-value for value in returns)
    rank = max(0, min(len(losses) - 1, math.ceil(confidence * len(losses)) - 1))
    var = losses[rank]
    tail = [loss for loss in losses if loss >= var]
    return max(0.0, var), max(0.0, sum(tail) / len(tail))


def _sample_stdev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    average = sum(values) / len(values)
    return math.sqrt(sum((value - average) ** 2 for value in values) / (len(values) - 1))


def _scenario_analytics(weighted: list[tuple], start_value: float, as_of: date) -> dict:
    monthly_returns = []
    benchmark_returns = []
    dated = []
    wealth = 1.0
    benchmark_wealth = 1.0
    peak = 1.0
    dates = [_month_end(as_of, back) for back in reversed(range(MODEL_MONTHS))]
    for index, on in enumerate(dates):
        portfolio_return = sum(
            weight * _scenario_asset_return(asset_id, asset_class, index)
            for asset_id, asset_class, weight, *_ in weighted
        )
        benchmark_return = _scenario_asset_return("BENCHMARK:SET50_MODEL_PROXY", "thai_equity", index)
        monthly_returns.append(portfolio_return)
        benchmark_returns.append(benchmark_return)
        wealth *= 1 + portfolio_return
        benchmark_wealth *= 1 + benchmark_return
        peak = max(peak, wealth)
        drawdown = wealth / peak - 1
        dated.append({
            "date": on.isoformat(),
            "growth_of_one": round(wealth, 6),
            "portfolio_value": round(start_value * wealth, 2),
            "benchmark_growth": round(benchmark_wealth, 6),
            "monthly_return": round(portfolio_return, 6),
            "drawdown": round(drawdown, 6),
        })

    annual: dict[str, float] = {}
    monthly_heatmap = []
    for point in dated:
        year = point["date"][:4]
        annual[year] = (1 + annual.get(year, 0.0)) * (1 + point["monthly_return"]) - 1
        monthly_heatmap.append({
            "year": int(year),
            "month": int(point["date"][5:7]),
            "return": point["monthly_return"],
        })

    rolling = []
    for index in range(11, len(dated)):
        window = monthly_returns[index - 11 : index + 1]
        rolling_return = math.prod(1 + value for value in window) - 1
        rolling.append({
            "date": dated[index]["date"],
            "return_12m": round(rolling_return, 6),
            "volatility_12m": round(_sample_stdev(window) * math.sqrt(12), 6),
        })

    worst = min(dated, key=lambda item: item["drawdown"])
    trough_index = dated.index(worst)
    peak_index = max(range(trough_index + 1), key=lambda idx: dated[idx]["growth_of_one"])
    recovery = next(
        (point for point in dated[trough_index + 1 :] if point["growth_of_one"] >= dated[peak_index]["growth_of_one"]),
        None,
    )
    return {
        "wealth": dated,
        "drawdown": [{"date": point["date"], "value": point["drawdown"]} for point in dated],
        "annual_returns": [{"year": int(year), "return": round(value, 6)} for year, value in sorted(annual.items())],
        "monthly_returns": monthly_heatmap,
        "rolling": rolling,
        "monthly_portfolio_returns": monthly_returns,
        "monthly_benchmark_returns": benchmark_returns,
        "drawdown_event": {
            "peak_date": dated[peak_index]["date"],
            "trough_date": worst["date"],
            "recovery_date": recovery["date"] if recovery else None,
            "drawdown": worst["drawdown"],
        },
    }


def _capped_weights(scores: list[tuple[str, float]]) -> list[dict]:
    if not scores:
        return []
    positive = [(asset_id, max(0.0, score)) for asset_id, score in scores]
    if sum(score for _, score in positive) <= 0:
        positive = [(asset_id, 1.0) for asset_id, _ in scores]
    remaining = WEIGHT_BPS_TOTAL
    active = dict(positive)
    output: dict[str, int] = {}
    while active and remaining > 0:
        total_score = sum(active.values()) or len(active)
        allocated_this_round = 0
        for asset_id in list(active):
            proposed = round(remaining * active[asset_id] / total_score)
            room = MAX_POSITION_BPS - output.get(asset_id, 0)
            amount = max(0, min(room, proposed, remaining - allocated_this_round))
            output[asset_id] = output.get(asset_id, 0) + amount
            allocated_this_round += amount
            if output[asset_id] >= MAX_POSITION_BPS:
                active.pop(asset_id)
        if allocated_this_round <= 0:
            break
        remaining -= allocated_this_round
    # Correct small rounding gaps without breaching the position cap.
    for asset_id in output:
        if remaining <= 0:
            break
        room = MAX_POSITION_BPS - output[asset_id]
        amount = min(room, remaining)
        output[asset_id] += amount
        remaining -= amount
    return [{"asset_id": asset_id, "weight_bps": weight} for asset_id, weight in output.items() if weight > 0]


def _model_allocations(weighted: list[tuple], target_volatility: float = 0.10) -> list[dict]:
    assets = [row for row in weighted if row[0] != "CASH:THB"]
    if not assets:
        return []
    equal = _capped_weights([(asset_id, 1.0) for asset_id, *_ in assets])
    minimum_variance = _capped_weights([(asset_id, 1 / max(volatility**2, 1e-6)) for asset_id, _, _, _, volatility, _ in assets])
    maximum_sharpe = _capped_weights([
        (asset_id, max(0.001, (annual_return - RISK_FREE_RATE) / max(volatility**2, 1e-6)))
        for asset_id, _, _, annual_return, volatility, _ in assets
    ])
    target = []
    max_sharpe_by_id = {row["asset_id"]: row["weight_bps"] for row in maximum_sharpe}
    estimated = math.sqrt(sum((max_sharpe_by_id.get(asset_id, 0) / WEIGHT_BPS_TOTAL * volatility) ** 2 for asset_id, _, _, _, volatility, _ in assets))
    scale = min(1.0, target_volatility / estimated) if estimated > 0 else 1.0
    for row in maximum_sharpe:
        target.append({"asset_id": row["asset_id"], "weight_bps": round(row["weight_bps"] * scale)})
    return [
        {"strategy": "EQUAL_WEIGHT", "label_th": "น้ำหนักเท่ากัน", "weights": equal},
        {"strategy": "MINIMUM_VARIANCE", "label_th": "ความผันผวนต่ำสุด (diagnostic)", "weights": minimum_variance},
        {"strategy": "MAXIMUM_SHARPE", "label_th": "Sharpe สูงสุด (diagnostic)", "weights": maximum_sharpe},
        {"strategy": "TARGET_VOLATILITY", "label_th": f"เป้าความผันผวน {target_volatility:.0%}", "weights": target},
    ]


def calculate_portfolio_analytics(client_id: str, weights: Optional[list[dict]] = None, goal_id: Optional[str] = None, gate: Optional[DataGate] = None) -> dict:
    gate = gate or get_gate()
    view = gate.client_view(client_id)
    if view is None:
        raise KeyError(f"unknown client: {client_id}")
    snapshot = portfolio_snapshot(view, gate)
    current_rows = [{"asset_id": h["asset_id"], "weight_bps": h["weight_bps"]} for h in snapshot["holdings"] if h["asset_id"] != "CASH:THB"]
    selected = validate_weights(weights if weights is not None else current_rows)
    weighted = []
    for row in selected["holdings"]:
        asset_class = _asset_class_for(row["asset_id"], snapshot, gate)
        annual_return, volatility, stress = _assumption(asset_class)
        weight = row["weight_bps"] / WEIGHT_BPS_TOTAL
        weighted.append((row["asset_id"], asset_class, weight, annual_return, volatility, stress))
    cash_weight = selected["residual_cash_bps"] / WEIGHT_BPS_TOTAL
    if cash_weight:
        ret, vol, stress = _assumption("cash")
        weighted.append(("CASH:THB", "cash", cash_weight, ret, vol, stress))
    expected_return = sum(w * r for _, _, w, r, _, _ in weighted)
    variance, covariance = _portfolio_variance(weighted)
    volatility = math.sqrt(variance)
    scenario = _scenario_analytics(weighted, snapshot["portfolio_value"], gate.as_of)
    returns = scenario["monthly_portfolio_returns"]
    benchmark_returns = scenario["monthly_benchmark_returns"]
    var95, cvar95 = _empirical_var_cvar(returns)
    downside = [min(value, 0.0) for value in returns]
    downside_deviation = math.sqrt(sum(value * value for value in downside) / len(downside)) * math.sqrt(12) if downside else 0.0
    total_return = scenario["wealth"][-1]["growth_of_one"] - 1 if scenario["wealth"] else 0.0
    cagr = (1 + total_return) ** (12 / max(1, len(returns))) - 1 if total_return > -1 else -1.0
    annual_returns = [row["return"] for row in scenario["annual_returns"]]
    max_drawdown = abs(min((row["value"] for row in scenario["drawdown"]), default=0.0))
    sharpe = (expected_return - RISK_FREE_RATE) / volatility if volatility > 1e-12 else None
    sortino = (expected_return - RISK_FREE_RATE) / downside_deviation if downside_deviation > 1e-12 else None
    calmar = cagr / max_drawdown if max_drawdown > 1e-12 else None
    benchmark_mean = sum(benchmark_returns) / len(benchmark_returns) if benchmark_returns else 0.0
    portfolio_mean = sum(returns) / len(returns) if returns else 0.0
    benchmark_variance = sum((value - benchmark_mean) ** 2 for value in benchmark_returns)
    beta = (sum((left - portfolio_mean) * (right - benchmark_mean) for left, right in zip(returns, benchmark_returns)) / benchmark_variance) if benchmark_variance > 1e-12 else None
    concentration = max((w for _, _, w, _, _, _ in weighted), default=0.0)
    calculation_id = _hash([client_id, goal_id, selected, gate.as_of.isoformat(), "portfolio_model_v2"], "calc")
    selected_goal = next((g for g in view.goals if g.goal_id == goal_id), None) if goal_id else None
    goals = [selected_goal] if selected_goal else list(view.goals)
    goal_impacts = [goal_outcome(g, gate.as_of, g.funded_amount, expected_return, volatility) for g in goals if g]
    asset_labels = [_asset_label(row[0], snapshot, gate) for row in weighted]
    correlation_matrix = [[round(_correlation(left[1], right[1], i == j), 4) for j, right in enumerate(weighted)] for i, left in enumerate(weighted)]
    risk_contributors = []
    for i, row in enumerate(weighted):
        contribution = row[2] * sum(covariance[i][j] * weighted[j][2] for j in range(len(weighted)))
        risk_contributors.append({
            "asset_id": row[0],
            "label": asset_labels[i],
            "variance_contribution": round(contribution, 8),
            "risk_share": round(contribution / variance, 6) if variance > 1e-12 else 0.0,
        })
    metrics = {
        "start_balance": round(snapshot["portfolio_value"], 2),
        "net_contribution": 0.0,
        "net_withdrawal": 0.0,
        "end_balance": scenario["wealth"][-1]["portfolio_value"] if scenario["wealth"] else round(snapshot["portfolio_value"], 2),
        "scenario_total_return": round(total_return, 6),
        "scenario_cagr": round(cagr, 6),
        "expected_return": round(expected_return, 6),
        "annual_volatility": round(volatility, 6),
        "best_year": round(max(annual_returns), 6) if annual_returns else None,
        "worst_year": round(min(annual_returns), 6) if annual_returns else None,
        "max_drawdown": round(max_drawdown, 6),
        "downside_deviation": round(downside_deviation, 6),
        "sharpe": round(sharpe, 4) if sharpe is not None else None,
        "sortino": round(sortino, 4) if sortino is not None else None,
        "calmar": round(calmar, 4) if calmar is not None else None,
        "scenario_var95_empirical": round(var95, 6),
        "scenario_cvar95_empirical": round(cvar95, 6),
        "beta_vs_model_benchmark": round(beta, 4) if beta is not None else None,
        "concentration": round(concentration, 6),
        "effective_holdings": round(1 / sum(w * w for _, _, w, _, _, _ in weighted), 3) if weighted else 0,
        "residual_cash_weight": cash_weight,
        "observation_count": len(returns),
        "max_drawdown_proxy": round(max_drawdown, 6),
        "var95_parametric": round(var95, 6),
        "cvar95_parametric": round(cvar95, 6),
        "sharpe_proxy": round(sharpe, 4) if sharpe is not None else None,
    }
    metric_metadata = {
        "expected_return": {"label_th": "ผลตอบแทนคาดหมาย", "meaning_th": "ค่าเฉลี่ยจากสมมติฐานรายสินทรัพย์ ใช้เปรียบเทียบทางเลือก ไม่ใช่คำรับประกัน", "formula": "weighted arithmetic assumptions", "period": "annual", "source": "DEMO_MODEL_ASSUMPTIONS", "limitation": "ไม่ใช่ผลตอบแทนในอนาคต"},
        "annual_volatility": {"label_th": "ความผันผวนต่อปี", "meaning_th": "ระดับการแกว่งของพอร์ตตาม covariance ที่กำกับไว้", "formula": "sqrt(w'Σw)", "period": "annual", "source": "LIVE_DETERMINISTIC_CALCULATOR", "limitation": "ขึ้นกับสมมติฐาน covariance"},
        "max_drawdown": {"label_th": "การลดลงสูงสุด", "meaning_th": "ช่วงลดลงมากที่สุดจากจุดสูงสุดถึงจุดต่ำสุดในเส้นทางแบบจำลอง", "formula": "min(W/running_peak-1)", "period": f"{MODEL_MONTHS} model months", "source": "DETERMINISTIC_MODEL_SCENARIO", "limitation": "ไม่ใช่ historical replay"},
        "scenario_var95_empirical": {"label_th": "Scenario VaR 95%", "meaning_th": "เกณฑ์ขาดทุนรายเดือนในส่วนหาง 5% ของเส้นทางแบบจำลอง", "formula": "empirical nearest-rank loss quantile", "period": "monthly", "source": "DETERMINISTIC_MODEL_SCENARIO", "limitation": "ไม่ใช่การคาดการณ์รายเดือนถัดไป"},
        "scenario_cvar95_empirical": {"label_th": "Scenario CVaR 95%", "meaning_th": "ขาดทุนเฉลี่ยเมื่อผลลัพธ์แบบจำลองอยู่ในส่วนที่แย่กว่า VaR", "formula": "mean(loss | loss >= VaR)", "period": "monthly", "source": "DETERMINISTIC_MODEL_SCENARIO", "limitation": "จำนวนข้อมูลจำลองจำกัด"},
        "effective_holdings": {"label_th": "จำนวนสินทรัพย์ที่กระจายจริง", "meaning_th": "จำนวนสินทรัพย์เชิงน้ำหนัก ไม่ใช่จำนวนบรรทัดที่ถือ", "formula": "1/sum(w²)", "period": "as-of", "source": "LIVE_DETERMINISTIC_CALCULATOR", "limitation": "ยังไม่รวม look-through ของกองทุน"},
        "sharpe": {"label_th": "Sharpe", "meaning_th": "ผลตอบแทนส่วนเกินต่อหนึ่งหน่วยความผันผวนตามสมมติฐานเดียวกัน", "formula": "(E[R]-Rf)/volatility", "period": "annual", "source": "LIVE_DETERMINISTIC_CALCULATOR", "limitation": "ไม่ควรใช้ลำพังเพื่อเลือกพอร์ต"},
        "sortino": {"label_th": "Sortino", "meaning_th": "ผลตอบแทนส่วนเกินเทียบกับความผันผวนด้านลบ", "formula": "(E[R]-Rf)/downside deviation", "period": "annual", "source": "LIVE_DETERMINISTIC_CALCULATOR", "limitation": "อิงเส้นทางแบบจำลอง"},
        "calmar": {"label_th": "Calmar", "meaning_th": "ผลตอบแทนทบต้นเทียบกับการลดลงสูงสุด", "formula": "CAGR/abs(MaxDD)", "period": f"{MODEL_MONTHS} model months", "source": "DETERMINISTIC_MODEL_SCENARIO", "limitation": "CAGR นี้มาจากแบบจำลอง ไม่ใช่ประวัติจริง"},
    }
    return {
        "context": client_workspace_context(view, gate, goal_id=goal_id, calculation_id=calculation_id),
        "calculation_id": calculation_id,
        "display_calculation_id": display_calculation_id(calculation_id, gate.as_of),
        "method": "DEMO_DETERMINISTIC_PORTFOLIO_MODEL_V2",
        "metrics": metrics,
        "metric_metadata": metric_metadata,
        "weights": [{"asset_id": asset_id, "label": _asset_label(asset_id, snapshot, gate), "asset_class": asset_class, "asset_class_label": ASSET_CLASS_LABELS.get(asset_class, asset_class), "weight": weight, "weight_bps": round(weight * WEIGHT_BPS_TOTAL)} for asset_id, asset_class, weight, *_ in weighted],
        "goal_impacts": goal_impacts,
        "chart_data": {
            "scenario_kind": "DETERMINISTIC_MODEL_SCENARIO",
            "scenario_label_th": "เส้นทางแบบจำลองเพื่อเปรียบเทียบ — ไม่ใช่ข้อมูลย้อนหลังหรือคำพยากรณ์",
            "wealth": scenario["wealth"],
            "drawdown": scenario["drawdown"],
            "annual_returns": scenario["annual_returns"],
            "monthly_returns": scenario["monthly_returns"],
            "rolling": scenario["rolling"],
            "drawdown_event": scenario["drawdown_event"],
        },
        "correlation": {"labels": asset_labels, "matrix": correlation_matrix, "method": "GOVERNED_CLASS_LEVEL_ASSUMPTION", "observation_count": len(returns)},
        "risk_contributors": sorted(risk_contributors, key=lambda row: abs(row["risk_share"]), reverse=True),
        "model_allocations": _model_allocations(weighted),
        "assumptions": {
            "version": "portfolio_model_v2",
            "return_convention": "annual arithmetic assumption plus deterministic model scenario; not historical replay or forecast",
            "covariance": "governed class-level correlation diagnostic; no forward-filled market returns",
            "risk_free_rate": RISK_FREE_RATE,
            "observation_frequency": "MONTHLY_MODEL_SCENARIO",
            "observation_count": len(returns),
            "market_identity_source": gate.eod_prices().source.upper(),
            "limitations": ["No complete contract-supported multi-asset history", "TWR and XIRR unavailable without reconciled dated cash flows", "Scenario metrics must not be labelled historical performance"],
        },
    }


class PortfolioDraftStore:
    """Small JSON-backed store so a saved draft survives a browser/API refresh."""

    def __init__(self, path: Optional[Path] = None) -> None:
        root = Path(os.getenv("RM_RUNTIME_DIR", Path.cwd() / ".runtime"))
        self.path = path or root / "portfolio_drafts.json"
        self._lock = Lock()

    def _read(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text())
            return payload if isinstance(payload, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _write(self, payload: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        temporary.replace(self.path)

    def list(self, client_id: str) -> list[dict]:
        return sorted([d for d in self._read().values() if d.get("client_id") == client_id], key=lambda d: d["updated_at"], reverse=True)

    def get(self, draft_id: str) -> Optional[dict]:
        return self._read().get(draft_id)

    def save(self, client_id: str, portfolio_id: str, weights: list[dict], draft_id: Optional[str] = None, calculation_id: Optional[str] = None) -> dict:
        validated = validate_weights(weights)
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            payload = self._read()
            existing = payload.get(draft_id or "")
            identifier = draft_id or f"draft_{uuid4().hex[:16]}"
            draft = {
                "client_id": client_id,
                "portfolio_id": portfolio_id,
                "draft_id": identifier,
                "created_at": existing["created_at"] if existing else now,
                "updated_at": now,
                "calculation_id": calculation_id,
                "model_version": "portfolio_builder_v24",
                "state": "DRAFT_PROPOSAL",
                "holdings": validated["holdings"],
                "total_weight_bps": validated["total_weight_bps"],
                "residual_cash_bps": validated["residual_cash_bps"],
                "current_portfolio_mutated": False,
                "human_approval_required": True,
                "auto_trade": False,
            }
            payload[identifier] = draft
            self._write(payload)
        return draft


@lru_cache
def get_draft_store() -> PortfolioDraftStore:
    return PortfolioDraftStore()
