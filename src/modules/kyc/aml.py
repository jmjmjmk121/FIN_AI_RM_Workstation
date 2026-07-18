"""Deterministic AML risk scoring and screening (ported methodology).

Adapted from the open `vyayasan/kyc-analyst` skill's four-factor risk model
(geographic 30% / customer profile 35% / product type 25% / channel 10%). That
project is a Claude Code analyst *plugin*, not an importable library, so this is
a clean-room port of its scoring methodology into the workstation's own
deterministic engine — it invents no live data and calls no external service.

Two of the four factors (geography, onboarding channel) have no field in the
synthetic Client 360 fixture. Rather than fabricate a fact, they are derived as
labelled SYNTHETIC_PROXY values, anchored to the KYC record's `aml_risk_rating`
so the explainable score reconciles with the rating of record. Sanctions/PEP
screening is reported as NOT_CONNECTED, matching how the rest of the repo marks
un-wired systems — no live list is queried, so no hit is ever asserted.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Optional

from data_gate.models import ClientView

# Weights are copied verbatim from the source skill's risk model.
FACTOR_WEIGHTS = {
    "geographic": 0.30,
    "customer_profile": 0.35,
    "product_type": 0.25,
    "channel": 0.10,
}

# Reference lists the screening step *would* consult once a connector is wired.
SCREENING_LISTS = ["OFAC_SDN", "UN_CONSOLIDATED", "EU_UK_HMT", "OPENSANCTIONS_PEP"]

# The rating of record anchors the two proxy factors so the computed band tracks it.
_RATING_ANCHOR = {"low": 14, "medium": 50, "high": 86, "unknown": 42}

_SEGMENT_BASE = {"Affluent": 16, "Priority": 26, "Private": 40, "Wealth": 52}
_MANDATE_BUMP = {"discretionary": 12, "advisory": 6, "execution_only": 0}
_RISK_WEIGHT = {
    "conservative": 10,
    "moderate": 35,
    "balanced": 48,
    "growth": 72,
    "aggressive": 92,
}
_ASSET_COMPLEXITY = {"commodity_etf": 8, "equity_etf": 4, "unit_trust": 2, "thai_equity": 2}


def _clamp(value: float) -> int:
    return int(round(max(0.0, min(100.0, value))))


def _jitter(seed: str, spread: int) -> int:
    """Stable pseudo-random offset in [-spread, spread] from a seed string."""
    digest = hashlib.sha256(seed.encode()).hexdigest()
    return (int(digest[:8], 16) % (2 * spread + 1)) - spread


@dataclass
class Factor:
    key: str
    label_th: str
    weight: float
    score: int
    rationale_th: str
    data_source: str

    @property
    def contribution(self) -> float:
        return round(self.score * self.weight, 1)

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "label_th": self.label_th,
            "weight": self.weight,
            "score": self.score,
            "contribution": self.contribution,
            "rationale_th": self.rationale_th,
            "data_source": self.data_source,
        }


def _customer_profile(view: ClientView) -> Factor:
    client = view.client
    score = _SEGMENT_BASE.get(client.segment, 40)
    score += _MANDATE_BUMP.get(client.mandate.value, 0)
    if client.is_vulnerable:
        score += 12
    if client.aum >= 50_000_000:
        score += 15
    elif client.aum >= 20_000_000:
        score += 8
    bits = [f"เซกเมนต์ {client.segment}", f"mandate {client.mandate.value}"]
    if client.is_vulnerable:
        bits.append("ลูกค้าเปราะบาง")
    if client.aum >= 20_000_000:
        bits.append("AUM สูง")
    return Factor(
        key="customer_profile",
        label_th="โปรไฟล์ลูกค้า",
        weight=FACTOR_WEIGHTS["customer_profile"],
        score=_clamp(score),
        rationale_th=", ".join(bits),
        data_source="SYNTHETIC_CLIENT_360",
    )


def _product_type(view: ClientView) -> Factor:
    holdings = view.client.holdings
    if not holdings:
        return Factor(
            key="product_type",
            label_th="ประเภทผลิตภัณฑ์",
            weight=FACTOR_WEIGHTS["product_type"],
            score=15,
            rationale_th="ไม่มีสถานะการลงทุน จึงถือความเสี่ยงผลิตภัณฑ์ต่ำ",
            data_source="SYNTHETIC_CLIENT_360",
        )
    total_mv = sum(h.market_value for h in holdings) or 1.0
    weighted = 0.0
    for h in holdings:
        base = _RISK_WEIGHT.get(h.risk_level.value, 40) + _ASSET_COMPLEXITY.get(h.asset_class, 0)
        weighted += min(100.0, base) * h.market_value
    score = weighted / total_mv
    top = max(holdings, key=lambda h: h.market_value)
    return Factor(
        key="product_type",
        label_th="ประเภทผลิตภัณฑ์",
        weight=FACTOR_WEIGHTS["product_type"],
        score=_clamp(score),
        rationale_th=f"ถ่วงน้ำหนักตามพอร์ต สัดส่วนหลักคือ {top.asset_class} ({top.risk_level.value})",
        data_source="SYNTHETIC_CLIENT_360",
    )


def _geographic(view: ClientView, anchor: int) -> Factor:
    # No country field exists in the fixture; derive a labelled proxy anchored to
    # the rating of record so the explanation stays consistent with it.
    score = _clamp(anchor + _jitter(view.client.client_id + "geo", 14))
    if score >= 66:
        place = "เขตอำนาจที่ต้องตรวจสอบเข้ม (proxy)"
    elif score >= 36:
        place = "ภูมิภาค ASEAN (proxy)"
    else:
        place = "ในประเทศ (TH, proxy)"
    return Factor(
        key="geographic",
        label_th="ความเสี่ยงเชิงภูมิศาสตร์",
        weight=FACTOR_WEIGHTS["geographic"],
        score=score,
        rationale_th=f"{place} — ไม่มีข้อมูลประเทศจริงในชุดข้อมูล",
        data_source="SYNTHETIC_PROXY",
    )


def _channel(view: ClientView, anchor: int) -> Factor:
    score = _clamp(anchor + _jitter(view.client.client_id + "chan", 18))
    if score >= 66:
        chan = "ผู้แนะนำ/ไม่พบหน้า (proxy)"
    elif score >= 36:
        chan = "เปิดบัญชีออนไลน์ (proxy)"
    else:
        chan = "เปิดที่สาขา/พบหน้า (proxy)"
    return Factor(
        key="channel",
        label_th="ช่องทางเปิดบัญชี",
        weight=FACTOR_WEIGHTS["channel"],
        score=score,
        rationale_th=f"{chan} — ไม่มีข้อมูลช่องทางจริงในชุดข้อมูล",
        data_source="SYNTHETIC_PROXY",
    )


# Threshold on the indicative score above which manual screening is required
# even if the stored rating is lower.
SCORE_SCREENING_THRESHOLD = 66


def score_aml(view: ClientView) -> dict:
    """Return the deterministic AML risk breakdown for one client.

    The KYC record's `aml_risk_rating` stays the authority (`rating_of_record`).
    The four-factor `score` is an indicative, explainable composite — it can
    exceed the stored rating, which is itself a useful signal that the rating on
    file may understate profile or product exposure.
    """
    rating = (view.kyc.aml_risk_rating if view.kyc else "unknown") or "unknown"
    anchor = _RATING_ANCHOR.get(rating, _RATING_ANCHOR["unknown"])
    factors = [
        _geographic(view, anchor),
        _customer_profile(view),
        _product_type(view),
        _channel(view, anchor),
    ]
    score = _clamp(sum(f.contribution for f in factors))
    # Screening escalates on either the indicative score or the rating of record.
    requires_screening = score >= SCORE_SCREENING_THRESHOLD or rating == "high"
    return {
        "score": score,
        "rating_of_record": rating,
        "score_exceeds_rating": score >= SCORE_SCREENING_THRESHOLD and rating != "high",
        "factors": [f.to_dict() for f in factors],
        "screening": {
            "sanctions_pep_status": "NOT_SCREENED_LIVE",
            "connector": "NOT_CONNECTED",
            "lists_reference": SCREENING_LISTS,
            "requires_manual_screening": requires_screening,
            "note_th": (
                "ต้องคัดกรอง Sanctions/PEP ด้วยมือก่อนอนุมัติ — ยังไม่ได้เชื่อมต่อรายชื่อจริง"
                if requires_screening
                else "จัดคิวคัดกรองตามรอบ — ยังไม่ได้เชื่อมต่อรายชื่อจริง"
            ),
        },
        "model": "AML_FOUR_FACTOR_V1",
        "human_review_required": True,
    }
