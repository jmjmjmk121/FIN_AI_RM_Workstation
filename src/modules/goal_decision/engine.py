"""Goal-conditioned product decision support.

This module implements the proposal's order of operations:

Goal Contract -> Hard Gates -> Deterministic Goal Impact -> Pareto Set -> RM decision.

It deliberately does not produce an opaque winner score. Products that fail a
hard gate remain visible as infeasible evidence, and every numeric comparison
is produced by the deterministic portfolio/goal calculator.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Optional

from data_gate.gate import DataGate, get_gate
from data_gate.models import Goal, RISK_RANK, RiskProfile
from modules.portfolio.engine import calculate_portfolio_analytics, goal_outcome
from modules.recommendation.engine import client_level_block, gate_product, load_catalog


RISK_TOLERANCE = {
    RiskProfile.CONSERVATIVE: 0.05,
    RiskProfile.MODERATE: 0.10,
    RiskProfile.BALANCED: 0.15,
    RiskProfile.GROWTH: 0.25,
    RiskProfile.AGGRESSIVE: 0.35,
}

PRODUCT_VOLATILITY = {
    RiskProfile.CONSERVATIVE: 0.025,
    RiskProfile.MODERATE: 0.070,
    RiskProfile.BALANCED: 0.120,
    RiskProfile.GROWTH: 0.185,
    RiskProfile.AGGRESSIVE: 0.260,
}

GOAL_QUESTIONS = {
    "goal_id": "ต้องการวางแผนสำหรับเป้าหมายใดของลูกค้า?",
    "client_confirmed": "ลูกค้ายืนยันจำนวนเงินและวันที่ของเป้าหมายนี้แล้วหรือยัง?",
    "planned_contribution": "ลูกค้าสามารถออมเพิ่มสำหรับเป้าหมายนี้เดือนละเท่าไร?",
    "acceptable_loss_pct": "หากพอร์ตลดลงชั่วคราว ลูกค้ารับการขาดทุนได้สูงสุดประมาณเท่าไร?",
    "capital_protection": "เงินต้นส่วนนี้จำเป็นต้องได้รับการคุ้มครองหรือไม่?",
    "complexity_tolerance": "ลูกค้ายอมรับผลิตภัณฑ์ที่ซับซ้อนและเงื่อนไขผลตอบแทนได้หรือไม่?",
}


def _calculation_id(payload: object) -> str:
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:16]
    return f"CAL-GOAL-{digest[:12].upper()}"


def _default_contract(goal: Goal, view, as_of: date) -> dict:
    client = view.client
    permission = view.permission
    return {
        "goal_id": goal.goal_id,
        "goal_name": goal.label,
        "target_amount": goal.target_amount,
        "target_date": goal.target_date.isoformat(),
        "required_cash_flow": max(0.0, goal.target_amount - goal.funded_amount),
        "current_allocated_wealth": goal.funded_amount,
        "planned_contribution": None,
        "liquidity_floor": client.liquidity_reserve_target,
        "emergency_reserve": client.liquidity_reserve_target,
        "acceptable_loss_pct": RISK_TOLERANCE[client.risk_profile],
        "risk_capacity": client.risk_profile.value,
        "risk_tolerance": client.risk_profile.value,
        "capital_protection": client.risk_profile == RiskProfile.CONSERVATIVE,
        "complexity_tolerance": bool(permission and "structured_note" in permission.allowed_product_types),
        "currency": "THB",
        "client_confirmed": goal.confirmed_with_client,
        "as_of": as_of.isoformat(),
        "source": "SYNTHETIC_CLIENT_GOAL_LEDGER",
    }


def _merge_contract(defaults: dict, supplied: Optional[dict]) -> dict:
    result = dict(defaults)
    for key, value in (supplied or {}).items():
        if value is not None:
            result[key] = value
    return result


def _clarifications(contract: dict) -> list[dict]:
    missing = []
    if not contract.get("client_confirmed"):
        missing.append("client_confirmed")
    if contract.get("planned_contribution") is None:
        missing.append("planned_contribution")
    return [
        {"field": field, "question": GOAL_QUESTIONS[field], "blocks_analysis": field == "client_confirmed"}
        for field in missing
    ]


def _product_detail(product, source_record) -> dict:
    return {
        "product_id": product.product_id,
        "name": product.name,
        "product_type": product.product_type,
        "risk_level": product.risk_level.value,
        "description": product.description,
        "features": product.features,
        "minimum_investment": product.min_investment,
        "liquidity_days": product.liquidity_days,
        "horizon_years": product.horizon_years,
        "indicative_return_pct": product.indicative_return_pct,
        "return_source": "DEMO_CATALOG_INDICATIVE_ASSUMPTION",
        "loss_mechanism": {
            "mutual_fund": "NAV may fall with the underlying assets; capital is not guaranteed.",
            "equity": "Market price may fall and the investor can lose capital.",
            "bond": "Credit, interest-rate and liquidity risk may reduce value before maturity.",
            "structured_note": "Payoff depends on contract terms and reference assets; principal may be at risk unless explicitly protected at maturity.",
            "deposit": "Early withdrawal may reduce interest; protection scope must follow applicable terms.",
            "insurance": "Early surrender can produce a value below premiums paid.",
            "financing": "Creates repayment and collateral obligations for the client.",
        }.get(product.product_type, "MISSING — confirm from approved product documents."),
        "fees": "MISSING — confirm from approved product documents.",
        "currency": source_record.currency,
        "approved_shelf_state": source_record.approved_shelf_state,
        "source": source_record.source,
        "as_of": "FIXTURE_VERSION_CURRENT",
        "factsheet": "NOT_SUPPORTED_BY_CURRENT_CONTRACT",
    }


def _impact(goal: Goal, as_of: date, return_pct: float, volatility: float, contribution: float) -> dict:
    return goal_outcome(
        goal,
        as_of,
        goal.funded_amount,
        return_pct / 100.0,
        volatility,
        monthly=contribution,
    )


def _classification(before: dict, after: dict) -> str:
    if after["expected_shortfall"] + 1 < before["expected_shortfall"]:
        return "IMPROVES_GOAL"
    if after["expected_shortfall"] > before["expected_shortfall"] + 1:
        return "WORSENS_GOAL"
    return "NEUTRAL_TO_GOAL"


def decide_for_goal(
    client_id: str,
    goal_id: str,
    goal_contract: Optional[dict] = None,
    gate: Optional[DataGate] = None,
) -> dict:
    gate = gate or get_gate()
    view = gate.client_view(client_id)
    if view is None:
        raise KeyError(f"unknown client: {client_id}")
    goal = next((item for item in view.goals if item.goal_id == goal_id), None)
    if goal is None:
        raise KeyError(f"unknown goal for client: {goal_id}")

    contract = _merge_contract(_default_contract(goal, view, gate.as_of), goal_contract)
    questions = _clarifications(contract)
    calculation_id = _calculation_id([client_id, goal_id, contract, gate.as_of.isoformat(), "goal_decision_v24"])
    if any(q["blocks_analysis"] for q in questions):
        return {
            "status": "NEED_GOAL_CLARIFICATION",
            "client_id": client_id,
            "goal_id": goal_id,
            "goal_contract": contract,
            "clarification_questions": questions,
            "calculation_id": calculation_id,
            "alternatives": [],
            "message": "ยังไม่ควรเลือกผลิตภัณฑ์ จนกว่าลูกค้าจะยืนยันเป้าหมาย จำนวนเงิน และกำหนดเวลา",
        }

    contribution = float(contract.get("planned_contribution") or 0)
    current = calculate_portfolio_analytics(client_id, goal_id=goal_id, gate=gate)
    before = current["goal_impacts"][0]
    records = {row.product_id: row for row in gate.products()}
    catalog = load_catalog(gate)
    client_block = client_level_block(view, gate.as_of)
    alternatives = []

    keep_cash = _impact(goal, gate.as_of, 1.5, 0.005, contribution)
    alternatives.append({
        "alternative_id": "KEEP_CASH",
        "category": "KEEP_CASH",
        "name": "คงเงินสดไว้ก่อน",
        "feasible": client_block is None,
        "hard_gate_reasons": [client_block] if client_block else [],
        "goal_classification": _classification(before, keep_cash),
        "goal_impact": keep_cash,
        "trade_off": "รักษาสภาพคล่อง แต่โอกาสปิดช่องว่างเป้าหมายอาจต่ำลง",
        "source": "DETERMINISTIC_GOAL_CALCULATOR",
    })

    portfolio_adjustment = goal_outcome(
        goal,
        gate.as_of,
        goal.funded_amount,
        current["metrics"]["expected_return"],
        current["metrics"]["annual_volatility"] * 0.90,
        monthly=contribution,
    )
    alternatives.append({
        "alternative_id": "PORTFOLIO_ADJUSTMENT",
        "category": "PORTFOLIO_ADJUSTMENT_PREFERRED",
        "name": "ปรับพอร์ตเดิมก่อนเลือกผลิตภัณฑ์เดี่ยว",
        "feasible": client_block is None,
        "hard_gate_reasons": [client_block] if client_block else [],
        "goal_classification": _classification(before, portfolio_adjustment),
        "goal_impact": portfolio_adjustment,
        "trade_off": "ลดความเสี่ยงรวมโดยใช้สินทรัพย์เดิม ต้องให้ RM จัดน้ำหนักและเปรียบเทียบก่อน",
        "href": f"/clients/{client_id}?section=portfolio&goalId={goal_id}",
        "source": "DETERMINISTIC_PORTFOLIO_CALCULATOR",
    })

    for product in catalog:
        product_gate = gate_product(product, view)
        reasons = ([client_block] if client_block else []) + product_gate.reasons
        relevant = goal.goal_type in product.goals_addressed
        if not relevant:
            reasons.append("ผลิตภัณฑ์ไม่รองรับเป้าหมายที่เลือก")
        if product.horizon_years > max(0.1, (goal.target_date - gate.as_of).days / 365.25):
            reasons.append("ระยะเวลาผลิตภัณฑ์ยาวกว่ากำหนดของเป้าหมาย")
        after = _impact(
            goal,
            gate.as_of,
            product.indicative_return_pct,
            PRODUCT_VOLATILITY[product.risk_level],
            contribution,
        )
        feasible = not reasons
        alternatives.append({
            "alternative_id": product.product_id,
            "category": "FEASIBLE_PRODUCT" if feasible else "INFEASIBLE",
            "name": product.name,
            "feasible": feasible,
            "hard_gate_reasons": reasons,
            "goal_classification": _classification(before, after) if feasible else "INFEASIBLE",
            "goal_impact": after,
            "trade_off": f"ผลตอบแทนสมมติฐาน {product.indicative_return_pct:.1f}% ต่อปี; ไม่ใช่การรับประกัน",
            "product": _product_detail(product, records[product.product_id]),
            "source": "DATA_GATE_DEMO_PRODUCT_CATALOG",
        })

    feasible = [a for a in alternatives if a["feasible"]]
    # A compact Pareto set: keep the alternatives that are best on shortfall or
    # liquidity. No single winner is asserted.
    best_shortfall = min((a["goal_impact"]["expected_shortfall"] for a in feasible), default=None)
    pareto_ids = [
        a["alternative_id"]
        for a in feasible
        if a["alternative_id"] == "KEEP_CASH"
        or a["goal_impact"]["expected_shortfall"] == best_shortfall
        or a["category"] == "PORTFOLIO_ADJUSTMENT_PREFERRED"
    ]
    return {
        "status": "READY" if not client_block else "BLOCKED",
        "client_id": client_id,
        "client_name": view.client.name,
        "goal_id": goal_id,
        "goal_contract": contract,
        "clarification_questions": questions,
        "current_goal_impact": before,
        "alternatives": alternatives,
        "pareto_alternative_ids": pareto_ids,
        "calculation_id": calculation_id,
        "model_version": "goal_conditioned_decision_v24",
        "assumption_version": "demo_goal_and_product_assumptions_v1",
        "reason_codes": ["GOAL_FIRST", "HARD_GATES_BEFORE_COMPARISON", "NO_OPAQUE_WINNER"],
        "human_decision_required": True,
        "auto_send": False,
        "auto_trade": False,
    }
