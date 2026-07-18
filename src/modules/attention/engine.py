"""Attention & Channel engine.

Decides who needs attention today and which lane they belong in.

The governing rule, from the project brief:

    Business value cannot override mandatory care, suitability, or
    client-benefit gates.

That is implemented literally. If a client has any mandatory care signal open,
the client is assigned the Care lane and their growth signals are *suppressed* —
they are recorded on the item as `suppressed_growth` so the RM can see what is
waiting, but they contribute nothing to the score and cannot pull the client
into the Growth lane. AUM never enters the score at all; a large client and a
small client with the same care signal rank the same.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from data_gate.gate import DataGate, get_gate
from data_gate.models import ClientView, Lane

from .signals import CARE_DETECTORS, GROWTH_DETECTORS, Signal

# Care always outranks growth in the ordering, regardless of any other factor.
LANE_BASE = {Lane.CARE: 1000.0, Lane.GROWTH: 0.0}
# Severity contributes this much per point.
SEVERITY_WEIGHT = 20.0
# A deadline inside this many days starts adding urgency.
URGENCY_HORIZON_DAYS = 90
URGENCY_WEIGHT = 30.0
# Each additional signal past the first adds a little, with diminishing returns.
STACKING_WEIGHT = 6.0


@dataclass
class AttentionItem:
    client_id: str
    client_name: str
    segment: str
    lane: Lane
    score: float
    headline: str
    next_best_action: str
    signals: list[Signal]
    suppressed_growth: list[Signal] = field(default_factory=list)
    contact_allowed: bool = True
    contact_block_reason: Optional[str] = None
    # Why this client landed in this lane, in plain words for the RM.
    lane_rationale: str = ""

    def to_dict(self) -> dict:
        def signal_dict(s: Signal) -> dict:
            return {
                "code": s.code,
                "lane": s.lane.value,
                "title": s.title,
                "detail": s.detail,
                "severity": s.severity,
                "days_to_deadline": s.days_to_deadline,
                "mandatory": s.mandatory,
                "evidence": s.evidence,
            }

        top_code = self.signals[0].code if self.signals else ""
        thai_title, thai_action = THAI_BY_CODE.get(top_code, (self.headline, self.next_best_action))
        return {
            "client_id": self.client_id,
            "client_name": self.client_name,
            "segment": self.segment,
            "lane": self.lane.value,
            "score": round(self.score, 2),
            "headline": self.headline,
            "headline_th": thai_title,
            "next_best_action": self.next_best_action,
            "next_best_action_th": thai_action,
            "lane_rationale": self.lane_rationale,
            "contact_allowed": self.contact_allowed,
            "contact_block_reason": self.contact_block_reason,
            "signals": [signal_dict(s) for s in self.signals],
            "suppressed_growth": [signal_dict(s) for s in self.suppressed_growth],
        }


ACTION_BY_CODE = {
    "KYC_MISSING": "Open a KYC file before any further activity",
    "KYC_OVERDUE": "Call to complete KYC renewal — advice is blocked until done",
    "KYC_DUE_SOON": "Send the KYC renewal pack and book a 15-minute call",
    "KYC_DOCUMENTS_MISSING": "Chase the outstanding KYC documents",
    "SUITABILITY_REVIEW_OVERDUE": "Re-run the suitability assessment",
    "SUITABILITY_CONFLICT": "Review the off-profile holdings and agree a remediation plan",
    "LIQUIDITY_SHORTFALL": "Discuss rebuilding the agreed cash reserve",
    "SEVERE_CONCENTRATION": "Present a diversification plan for the concentrated position",
    "CRITICAL_GOAL_AT_RISK": "Re-plan the goal — revise contribution, timing, or target",
    "VULNERABLE_CLIENT_NEED": "Welfare check with enhanced-care handling",
    "UNRESOLVED_SERVICE_ISSUE": "Resolve the open service issue and close the loop",
    "EXCESS_LIQUIDITY": "Discuss deploying idle cash held above the reserve",
    "MATURED_INVESTMENT": "Reinvestment conversation — proceeds are sitting idle",
    "MATURING_INVESTMENT": "Prepare reinvestment options ahead of maturity",
    "RETIREMENT_PLANNING_NEED": "Review the retirement funding plan",
    "PROTECTION_GAP": "Review protection cover against the confirmed gap",
    "FINANCING_NEED": "Explore financing options for the confirmed need",
    "TAX_EVENT": "Review tax-efficient allocation before the window closes",
}

THAI_BY_CODE = {
    "KYC_MISSING": ("ยังไม่มีข้อมูล KYC", "เปิดแฟ้ม KYC และยืนยันข้อมูลก่อนทำคำแนะนำ"),
    "KYC_OVERDUE": ("KYC หมดอายุ", "ติดต่อลูกค้าเพื่อต่ออายุ KYC ก่อนให้คำแนะนำ"),
    "KYC_DUE_SOON": ("KYC ใกล้ครบกำหนด", "เตรียมเอกสารต่ออายุและนัดหมายลูกค้า"),
    "KYC_DOCUMENTS_MISSING": ("เอกสาร KYC ยังไม่ครบ", "ขอเอกสารที่ขาดให้ครบก่อนดำเนินการ"),
    "SUITABILITY_REVIEW_OVERDUE": ("Suitability หมดอายุ", "ประเมิน Suitability ใหม่ก่อนเสนอผลิตภัณฑ์"),
    "SUITABILITY_CONFLICT": ("พอร์ตขัดกับกรอบความเสี่ยง", "ทบทวนสินทรัพย์ที่เกินกรอบและจัดทำแผนแก้ไข"),
    "LIQUIDITY_SHORTFALL": ("เงินสำรองต่ำกว่ากรอบ", "หารือการเติมเงินสำรองก่อนเพิ่มความเสี่ยง"),
    "SEVERE_CONCENTRATION": ("พอร์ตกระจุกตัวสูง", "เตรียมทางเลือกกระจายความเสี่ยงให้ RM พิจารณา"),
    "CRITICAL_GOAL_AT_RISK": ("เป้าหมายสำคัญมีความเสี่ยง", "ทบทวนเงินออม ระยะเวลา หรือจำนวนเงินเป้าหมาย"),
    "VULNERABLE_CLIENT_NEED": ("ลูกค้าต้องได้รับการดูแลเป็นพิเศษ", "ติดต่อด้วยขั้นตอน enhanced care"),
    "UNRESOLVED_SERVICE_ISSUE": ("มีเรื่องบริการค้าง", "แก้เรื่องบริการและแจ้งผลลูกค้าก่อนงานขาย"),
    "EXCESS_LIQUIDITY": ("มีเงินสดเหนือเงินสำรอง", "ยืนยันเป้าหมายก่อนพิจารณานำเงินส่วนเกินไปใช้"),
    "MATURED_INVESTMENT": ("สินทรัพย์ครบกำหนดแล้ว", "ทบทวนความต้องการก่อนเสนอทางเลือกลงทุนต่อ"),
    "MATURING_INVESTMENT": ("สินทรัพย์ใกล้ครบกำหนด", "เตรียมทางเลือกก่อนวันครบกำหนด"),
    "RETIREMENT_PLANNING_NEED": ("ควรทบทวนเป้าหมายเกษียณ", "ยืนยัน Goal Contract และช่องว่างเงินเกษียณ"),
    "PROTECTION_GAP": ("มีช่องว่างความคุ้มครอง", "ทบทวนความคุ้มครองและส่งต่อผู้เชี่ยวชาญเมื่อจำเป็น"),
    "FINANCING_NEED": ("มีความต้องการด้านสินเชื่อ", "ยืนยันกระแสเงินสดและส่งต่อผู้เชี่ยวชาญสินเชื่อ"),
    "TAX_EVENT": ("ใกล้ช่วงวางแผนภาษี", "ทบทวนเป้าหมายและเงื่อนไขก่อนพิจารณาทางเลือก"),
}


def _urgency(signal: Signal) -> float:
    """0..1. Overdue is maximal; far-off deadlines contribute nothing."""
    days = signal.days_to_deadline
    if days is None:
        return 0.0
    if days <= 0:
        return 1.0
    if days >= URGENCY_HORIZON_DAYS:
        return 0.0
    return 1.0 - (days / URGENCY_HORIZON_DAYS)


def score_signals(lane: Lane, signals: list[Signal]) -> float:
    if not signals:
        return 0.0
    top = max(signals, key=lambda s: (s.severity, _urgency(s)))
    score = LANE_BASE[lane]
    score += top.severity * SEVERITY_WEIGHT
    score += _urgency(top) * URGENCY_WEIGHT
    # Stacking: more open signals means a fuller conversation, but one severe
    # signal should still beat several mild ones — hence the sqrt-ish taper.
    extra = len(signals) - 1
    score += (extra**0.5) * STACKING_WEIGHT if extra > 0 else 0.0
    return score


def evaluate_client(view: ClientView, as_of: date, gate: DataGate) -> Optional[AttentionItem]:
    care: list[Signal] = []
    for detector in CARE_DETECTORS:
        care.extend(detector(view, as_of))

    growth: list[Signal] = []
    for detector in GROWTH_DETECTORS:
        growth.extend(detector(view, as_of))

    if not care and not growth:
        return None

    decision = gate.contact_decision(view)
    mandatory_care = [s for s in care if s.mandatory]

    if mandatory_care:
        # The whole rule, in one branch: care wins, growth is set aside.
        lane = Lane.CARE
        active, suppressed = care, growth
        codes = ", ".join(sorted({s.code for s in mandatory_care}))
        rationale = (
            f"Mandatory care gate open ({codes}). "
            "Growth activity is suppressed until it is cleared."
            if growth
            else f"Mandatory care gate open ({codes})."
        )
    else:
        lane = Lane.GROWTH
        active, suppressed = growth, []
        rationale = "No care gate open; confirmed or evidenced growth need."

    if not active:
        return None

    score = score_signals(lane, active)
    top = max(active, key=lambda s: (s.severity, _urgency(s)))

    # A client we may not contact still surfaces if care is open — the RM needs
    # to know the gate exists — but never outranks someone we can actually help.
    if not decision.allowed:
        if lane == Lane.GROWTH:
            return None
        score -= 500.0

    return AttentionItem(
        client_id=view.client.client_id,
        client_name=view.client.name,
        segment=view.client.segment,
        lane=lane,
        score=score,
        headline=top.title,
        next_best_action=ACTION_BY_CODE.get(top.code, "Review client file"),
        signals=sorted(active, key=lambda s: (-s.severity, s.code)),
        suppressed_growth=sorted(suppressed, key=lambda s: (-s.severity, s.code)),
        contact_allowed=decision.allowed,
        contact_block_reason=decision.reason,
        lane_rationale=rationale,
    )


def build_attention_list(
    rm_id: Optional[str] = None,
    lane: Optional[Lane] = None,
    limit: Optional[int] = None,
    gate: Optional[DataGate] = None,
) -> list[AttentionItem]:
    gate = gate or get_gate()
    as_of = gate.as_of
    rm_id = rm_id or gate.settings.rm_id

    items = []
    for view in gate.client_views(rm_id):
        item = evaluate_client(view, as_of, gate)
        if item is not None:
            items.append(item)

    if lane is not None:
        items = [i for i in items if i.lane == lane]

    items.sort(key=lambda i: -i.score)
    return items[:limit] if limit else items


def build_daily_review_queue(
    items: list[AttentionItem],
    limit: int,
    care_limit: int,
) -> list[AttentionItem]:
    """Build the bounded candidate set shown to the RM each day.

    The attention engine still evaluates the entire book.  This function only
    applies workstation capacity after scoring, keeps Care ahead of Growth in
    the final order, and reserves a visible Growth lane without letting AUM or
    product value displace the configured Care allocation.
    """
    if limit <= 0:
        return []
    care = [item for item in items if item.lane == Lane.CARE]
    growth = [item for item in items if item.lane == Lane.GROWTH]
    selected = care[: min(care_limit, limit)]
    selected.extend(growth[: max(0, limit - len(selected))])

    if len(selected) < limit:
        selected_ids = {item.client_id for item in selected}
        remainder = [item for item in items if item.client_id not in selected_ids]
        selected.extend(remainder[: limit - len(selected)])

    selected.sort(key=lambda item: -item.score)
    return selected


def summarise(items: list[AttentionItem]) -> dict:
    care = [i for i in items if i.lane == Lane.CARE]
    growth = [i for i in items if i.lane == Lane.GROWTH]
    return {
        "total": len(items),
        "care": len(care),
        "growth": len(growth),
        "blocked": len([i for i in items if not i.contact_allowed]),
        "suppressed_growth_clients": len([i for i in care if i.suppressed_growth]),
        "top_signal_codes": _count_codes(items),
    }


def _count_codes(items: list[AttentionItem]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        for signal in item.signals:
            counts[signal.code] = counts.get(signal.code, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))
