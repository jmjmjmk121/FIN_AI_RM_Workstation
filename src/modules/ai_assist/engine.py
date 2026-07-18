"""Grounded RM brief and conversation draft.

No LLM provider is configured in this repository. This deterministic fallback
creates the exact governed input/output seam an approved LLM can later use,
while ensuring every number is copied from a calculator result with metadata.
"""

from __future__ import annotations

import hashlib
import json
from typing import Optional

from data_gate.gate import DataGate, get_gate
from modules.activity.engine import build_activity_dashboard
from modules.attention.engine import build_attention_list, build_daily_review_queue
from modules.goal_decision.engine import decide_for_goal
from modules.portfolio.engine import calculate_portfolio_analytics


def build_rm_brief(client_id: str, goal_id: Optional[str] = None, gate: Optional[DataGate] = None) -> dict:
    gate = gate or get_gate()
    view = gate.client_view(client_id)
    if view is None:
        raise KeyError(f"unknown client: {client_id}")
    goal = next((goal for goal in view.goals if goal.goal_id == goal_id), None) if goal_id else None
    goal = goal or (view.goals[0] if view.goals else None)
    analytics = calculate_portfolio_analytics(client_id, goal_id=goal.goal_id if goal else None, gate=gate)
    attention = next((row.to_dict() for row in build_attention_list(gate=gate) if row.client_id == client_id), None)
    impact = analytics["goal_impacts"][0] if analytics["goal_impacts"] else None
    goal_name = goal.label if goal else "เป้าหมายที่ต้องยืนยัน"
    why_client = (attention or {}).get("headline_th", "ถึงรอบทบทวนข้อมูลลูกค้า")
    why_now = (attention or {}).get("next_best_action_th", "ยืนยันเป้าหมายและข้อมูลล่าสุดก่อนวิเคราะห์")
    questions = [
        f"เป้าหมาย “{goal_name}” จำนวนเงินและวันที่ยังตรงกับความต้องการปัจจุบันหรือไม่?",
        "เงินสำรองที่ต้องเก็บไว้ใช้ระยะสั้นมีจำนวนเท่าไร และห้ามนำไปลงทุนเท่าไร?",
        "หากมูลค่าพอร์ตลดลงชั่วคราว ลูกค้ารับได้มากที่สุดประมาณเท่าไร?",
    ]
    if goal and not goal.confirmed_with_client:
        questions.insert(0, "ขอให้ลูกค้ายืนยัน Goal Contract ก่อนเปรียบเทียบผลิตภัณฑ์")
    shortfall_text = f"ช่องว่างตามเครื่องคำนวณประมาณ {impact['expected_shortfall']:,.0f} บาท" if impact else "ยังคำนวณช่องว่างไม่ได้"
    return {
        "client_id": client_id,
        "goal_id": goal.goal_id if goal else None,
        "mode": "GOVERNED_AI_TEMPLATE_FALLBACK",
        "live_llm_connected": False,
        "why_client": why_client,
        "why_need": f"เป้าหมายที่กำลังพิจารณาคือ {goal_name}",
        "why_solution": "ให้ RM เปรียบเทียบคงเงินสด ปรับพอร์ต และผลิตภัณฑ์ที่ผ่าน hard gates โดยไม่เลือกผู้ชนะอัตโนมัติ",
        "why_now": why_now,
        "questions": questions[:3],
        "draft_message": f"สวัสดีครับ/ค่ะ ขออนุญาตนัดทบทวนเป้าหมาย {goal_name} และข้อมูลความเสี่ยงล่าสุด เพื่อดูว่าพอร์ตปัจจุบันยังเหมาะสมหรือไม่ โดย {shortfall_text} ข้อความนี้เป็นร่างให้ RM ตรวจแก้ก่อนใช้",
        "do_not_say": ["ผลตอบแทนรับประกัน", "ผลิตภัณฑ์นี้ดีที่สุด", "ระบบอนุมัติให้แล้ว"],
        "numeric_evidence": [
            {
                "name": "expected_shortfall",
                "value": impact["expected_shortfall"] if impact else None,
                "unit": "THB",
                "asOf": gate.as_of.isoformat(),
                "sourceRefs": ["SYNTHETIC_GOAL_LEDGER", analytics["method"]],
                "formulaId": impact["method"] if impact else None,
                "calculationId": analytics["calculation_id"],
                "modelVersion": "portfolio_builder_v24",
                "assumptionVersion": analytics["assumptions"]["version"],
                "inputHash": analytics["calculation_id"].replace("calc_", ""),
                "reasonCodes": ["GOAL_SHORTFALL", "VALIDATED_CALCULATOR_ONLY"],
            }
        ],
        "human_review_required": True,
        "auto_send": False,
        "auto_trade": False,
    }


def build_client_message_draft(
    client_id: str,
    situation: str = "PANIC_MARKET_DROP",
    goal_id: Optional[str] = None,
    gate: Optional[DataGate] = None,
) -> dict:
    """Create a governed LINE-ready draft without sending it.

    The structure follows a low-noise information sequence: acknowledge the
    emotion, separate known facts from unknown client state, then ask for one
    reversible next step. It does not claim that information theory proves a
    persuasive script and it never supplies calculator numbers free-form.
    """
    gate = gate or get_gate()
    view = gate.client_view(client_id)
    if view is None:
        raise KeyError(f"unknown client: {client_id}")
    goal = next((item for item in view.goals if item.goal_id == goal_id), None) if goal_id else None
    goal = goal or (view.goals[0] if view.goals else None)
    analytics = calculate_portfolio_analytics(client_id, goal_id=goal.goal_id if goal else None, gate=gate)
    goal_name = goal.label if goal else "เป้าหมายที่ต้องยืนยัน"
    client_name = view.client.name
    situation_copy = {
        "PANIC_MARKET_DROP": {
            "opening": "เข้าใจว่าตลาดที่ผันผวนอาจทำให้กังวลและอยากตัดสินใจทันทีได้ครับ/ค่ะ",
            "known": f"ข้อมูลที่ระบบยืนยันได้ตอนนี้คือ เรากำลังทบทวนพอร์ตเทียบกับเป้าหมาย “{goal_name}” โดยยังไม่มีการส่งคำสั่งซื้อขาย",
            "unknown": "สิ่งที่ยังต้องยืนยันคือ วันใช้เงินจริง เงินสำรองที่ห้ามแตะ และระดับการลดลงที่คุณยังรับได้",
            "question": "สะดวกคุยสั้น ๆ เพื่อเทียบทางเลือกคงพอร์ต ลดความเสี่ยง และเพิ่มสภาพคล่องก่อนตัดสินใจไหมครับ/คะ?",
        },
        "GOAL_REVIEW": {
            "opening": "ขออนุญาตทบทวนเป้าหมายและพอร์ตตามรอบครับ/ค่ะ",
            "known": f"ระบบเชื่อมพอร์ตปัจจุบันกับเป้าหมาย “{goal_name}” เพื่อให้เห็นผลกระทบของแต่ละทางเลือก",
            "unknown": "ต้องยืนยันจำนวนเงิน วันที่ต้องใช้ และข้อจำกัดสภาพคล่องล่าสุดก่อนเสนอทางเลือก",
            "question": "ข้อมูลเป้าหมายและเงินสำรองที่เคยยืนยันไว้ยังตรงกับวันนี้หรือไม่ครับ/คะ?",
        },
        "INACTIVE_REENGAGEMENT": {
            "opening": "ไม่ได้ติดต่อกันสักระยะ จึงอยากขอเช็กว่าความต้องการทางการเงินเปลี่ยนไปหรือไม่ครับ/ค่ะ",
            "known": f"พอร์ตยังมีรายการเชื่อมกับเป้าหมาย “{goal_name}” และระบบยังไม่ได้ดำเนินการใดแทนคุณ",
            "unknown": "ยังไม่ทราบว่าเงินก้อนนี้มีแผนใช้ใหม่ หรือประสงค์ให้ทบทวนความเสี่ยงหรือไม่",
            "question": "ต้องการให้ผม/ดิฉันสรุปสถานะสั้น ๆ หรือสะดวกนัดคุยก่อนครับ/คะ?",
        },
    }
    copy = situation_copy.get(situation, situation_copy["GOAL_REVIEW"])
    draft_message = f"สวัสดีคุณ{client_name} {copy['opening']} {copy['known']} {copy['unknown']} {copy['question']}"
    raw_id = hashlib.sha256(json.dumps([client_id, goal_name, situation, gate.as_of.isoformat()], ensure_ascii=False).encode()).hexdigest()
    return {
        "message_id": f"msg_{raw_id[:16]}",
        "client_id": client_id,
        "goal_id": goal.goal_id if goal else None,
        "channel": "LINE",
        "situation": situation,
        "status": "DRAFT_REQUIRES_RM_REVIEW",
        "draft_message": draft_message,
        "information_design": {
            "known": copy["known"],
            "unknown": copy["unknown"],
            "next_action": copy["question"],
            "principle": "ลดข้อมูลรบกวน แยกสิ่งที่รู้/ยังไม่รู้ และเสนอ next step เดียวที่ย้อนกลับได้",
        },
        "psychology_guardrails": [
            "ยอมรับความกังวลโดยไม่ตอกย้ำความกลัว",
            "ไม่รับประกัน ไม่บอกให้รีบขาย และไม่ทำให้ลูกค้ารู้สึกถูกกดดัน",
            "ให้ลูกค้ายังคงสิทธิเลือก และขอข้อมูลเพิ่มก่อนแนะนำ",
            "เปรียบเทียบหลายทางเลือกด้วยเครื่องคำนวณชุดเดียว",
        ],
        "review_checks": [
            {"code": "EMPATHY_WITHOUT_ALARM", "label_th": "รับฟังความกังวลโดยไม่เพิ่มความตื่นตระหนก", "passed": True},
            {"code": "KNOWN_UNKNOWN_NEXT", "label_th": "แยกสิ่งที่รู้ สิ่งที่ยังไม่รู้ และสิ่งที่ทำต่อ", "passed": True},
            {"code": "NO_GUARANTEE_OR_PRESSURE", "label_th": "ไม่มีคำรับประกันหรือเร่งให้ซื้อขาย", "passed": True},
            {"code": "ONE_CLEAR_QUESTION", "label_th": "มีคำถามถัดไปที่ชัดเจนหนึ่งเรื่อง", "passed": True},
            {"code": "RM_REVIEW", "label_th": "RM ต้องอ่าน แก้ และยืนยันก่อนนำไปใช้", "passed": False},
        ],
        "numeric_evidence": [],
        "source_refs": [
            {"source": "SYNTHETIC_CLIENT_360", "as_of": gate.as_of.isoformat()},
            {"source": analytics["method"], "calculation_id": analytics["calculation_id"], "display_id": analytics["display_calculation_id"]},
            {"source": gate.eod_prices().source.upper(), "as_of": gate.eod_prices().as_of.isoformat()},
        ],
        "human_review_required": True,
        "rm_can_edit": True,
        "auto_send": False,
        "auto_trade": False,
        "line_connector": "NOT_CONFIGURED",
    }


def build_book_product_opportunities(
    rm_id: Optional[str] = None,
    limit: int = 6,
    gate: Optional[DataGate] = None,
) -> dict:
    """Prepare goal-conditioned product conversations for an RM book.

    This is governed orchestration, not free-form advice: activity evidence
    selects a review moment, Goal Contract selects the need, the rule engine
    removes infeasible products, and the deterministic calculator supplies all
    goal-impact numbers. No single product is declared a winner.
    """
    gate = gate or get_gate()
    all_views = gate.client_views(rm_id or gate.settings.rm_id)
    views_by_id = {view.client.client_id: view for view in all_views}
    activity_by_client = {
        row["client_id"]: row
        for row in build_activity_dashboard(rm_id=rm_id, gate=gate)["rows"]
    }
    attention_rows = build_attention_list(rm_id=rm_id, gate=gate)
    attention_by_client = {row.client_id: row.to_dict() for row in attention_rows}
    review_rows = build_daily_review_queue(
        attention_rows,
        limit=gate.settings.rm_daily_review_limit,
        care_limit=gate.settings.rm_daily_care_review_limit,
    )
    # Product preparation is downstream of Attention & Channel.  It must not
    # recalculate every portfolio in a 300-client book on each dashboard load.
    # Evaluate the bounded, governed review set in the exact attention order.
    views = [views_by_id[row.client_id] for row in review_rows]
    prepared = []
    needs_confirmation = 0
    blocked = 0

    for view in views:
        activity = activity_by_client[view.client.client_id]
        confirmed_goals = [goal for goal in view.goals if goal.confirmed_with_client]
        if not confirmed_goals:
            needs_confirmation += 1
            continue
        goal = sorted(confirmed_goals, key=lambda item: (item.priority, item.target_date))[0]
        decision = decide_for_goal(
            view.client.client_id,
            goal.goal_id,
            {"client_confirmed": True, "planned_contribution": 0},
            gate=gate,
        )
        if decision["status"] != "READY":
            blocked += 1
            continue

        feasible_products = [
            alternative
            for alternative in decision["alternatives"]
            if alternative.get("feasible") and alternative.get("product")
        ]
        feasible_products.sort(
            key=lambda item: (
                item["alternative_id"] not in decision["pareto_alternative_ids"],
                item["goal_impact"]["expected_shortfall"],
                item["product"]["minimum_investment"],
            )
        )
        attention = attention_by_client.get(view.client.client_id, {})
        latest_kind = activity.get("last_activity_kind")
        latest_on = activity.get("last_activity_on")
        why_now = activity.get("reengagement_reason")
        if not why_now and latest_kind and latest_on:
            kind_th = {"deposit": "ฝากเงิน", "withdrawal": "ถอนเงิน", "trade": "ซื้อขาย"}.get(latest_kind, latest_kind)
            why_now = f"มีกิจกรรม{kind_th}ล่าสุดเมื่อ {latest_on} จึงควรทบทวนว่าเป้าหมายยังเหมาะสมหรือไม่"
        why_now = why_now or "ถึงรอบทบทวน Goal Contract และพอร์ตตามข้อมูลล่าสุด"

        product_candidates = [
            {
                "product_id": item["alternative_id"],
                "name": item["name"],
                "product_type": item["product"]["product_type"],
                "source": item["product"]["source"],
                "goal_classification": item["goal_classification"],
                "expected_shortfall": item["goal_impact"]["expected_shortfall"],
            }
            for item in feasible_products[:2]
        ]
        solution_type = "PRODUCT_REVIEW" if product_candidates else "PORTFOLIO_OR_PLANNING_REVIEW"
        prepared.append({
            "client_id": view.client.client_id,
            "client_name": view.client.name,
            "segment": view.client.segment,
            "activity_status": activity["status"],
            "investment_activity": activity["investment_activity"],
            "last_activity_kind": latest_kind,
            "last_activity_on": latest_on,
            "investable_cash": view.client.investable_cash,
            "goal_id": goal.goal_id,
            "goal_name": goal.label,
            "why_now": why_now,
            "why_client": attention.get("headline_th") or "มี activity/goal evidence ที่ควรให้ RM ทบทวน",
            "solution_type": solution_type,
            "product_candidates": product_candidates,
            "next_step": "ให้ RM ตรวจ Product Evidence และ hard gates ก่อนคุยกับลูกค้า" if product_candidates else "ให้ RM ทบทวนพอร์ตหรือส่งต่อผู้เชี่ยวชาญก่อนเลือก Product",
            "href": f"/products?clientId={view.client.client_id}&goalId={goal.goal_id}",
            "calculation_id": decision["calculation_id"],
            "human_decision_required": True,
            "auto_send": False,
            "auto_trade": False,
            "_sort": (
                0 if activity["matured_value"] > 0 else 1,
                0 if activity["investment_activity"] in {"active_cash_flow", "active_trading"} else 1,
                0 if product_candidates else 1,
                -view.client.investable_cash,
            ),
        })

    prepared.sort(key=lambda item: item["_sort"])
    for item in prepared:
        item.pop("_sort", None)
    return {
        "as_of": gate.as_of.isoformat(),
        "mode": "GOVERNED_AI_ORCHESTRATION",
        "live_llm_connected": False,
        "items": prepared[:limit],
        "summary": {
            "ready_for_rm_review": len(prepared),
            "needs_goal_confirmation": needs_confirmation,
            "blocked_by_hard_gate": blocked,
            "screened_candidates": len(views),
            "full_book_clients": len(all_views),
        },
        "human_decision_required": True,
        "auto_send": False,
        "auto_trade": False,
    }
