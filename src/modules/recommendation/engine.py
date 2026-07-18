"""Product Recommendation module.

Input: a client plus the goals/needs the RM wants to address.
Output: a ranked list of products that fit, and — just as important — the list
of products that were ruled out, each with the reason.

Design decision: gates run before scoring, and a gated product can never be
recommended no matter how well it scores. The brief's rule that business value
cannot override a client-benefit gate applies here as much as in Module 1, so
the same shape is used: hard gates first, ranking only among survivors.

Nothing here calls a model. The gates are deterministic and auditable, which is
what a suitability decision has to be.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from data_gate.gate import DataGate, get_gate
from data_gate.models import (
    RISK_RANK,
    ClientView,
    GoalType,
    KycStatus,
    Mandate,
    RiskProfile,
)

# Weights for the fit score. Goal match dominates; the rest are refinements.
W_GOAL_MATCH = 50.0
W_RISK_FIT = 20.0
W_HORIZON_FIT = 15.0
W_AFFORDABILITY = 10.0
W_LIQUIDITY_FIT = 5.0


@dataclass
class Product:
    product_id: str
    name: str
    product_type: str
    risk_level: RiskProfile
    goals_addressed: list[GoalType]
    min_investment: float
    liquidity_days: int
    horizon_years: float
    indicative_return_pct: float
    description: str
    features: list[str] = field(default_factory=list)


@dataclass
class GateResult:
    passed: bool
    reasons: list[str] = field(default_factory=list)


@dataclass
class Recommendation:
    product: Product
    score: float
    rationale: list[str]
    cautions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "product_id": self.product.product_id,
            "name": self.product.name,
            "product_type": self.product.product_type,
            "risk_level": self.product.risk_level.value,
            "min_investment": self.product.min_investment,
            "liquidity_days": self.product.liquidity_days,
            "horizon_years": self.product.horizon_years,
            "indicative_return_pct": self.product.indicative_return_pct,
            "description": self.product.description,
            "features": self.product.features,
            "score": round(self.score, 1),
            "rationale": self.rationale,
            "cautions": self.cautions,
        }


@dataclass
class ExcludedProduct:
    product: Product
    reasons: list[str]

    def to_dict(self) -> dict:
        return {
            "product_id": self.product.product_id,
            "name": self.product.name,
            "product_type": self.product.product_type,
            "risk_level": self.product.risk_level.value,
            "reasons": self.reasons,
        }


def load_catalog(gate: Optional[DataGate] = None) -> list[Product]:
    rows = (gate or get_gate()).products()
    return [
        Product(
            product_id=r.product_id,
            name=r.name,
            product_type=r.product_type,
            risk_level=r.risk_level,
            goals_addressed=list(r.goals_addressed),
            min_investment=float(r.min_investment),
            liquidity_days=int(r.liquidity_days),
            horizon_years=float(r.horizon_years),
            indicative_return_pct=float(r.indicative_return_pct),
            description=r.description,
            features=list(r.features),
        )
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Hard gates. A failure here is final.
# ---------------------------------------------------------------------------


def client_level_block(view: ClientView, as_of: date) -> Optional[str]:
    """Reasons no product at all may be recommended to this client.

    This is the client-benefit gate. It runs before the catalog is even read.
    """
    kyc = view.kyc
    if kyc is None:
        return "No KYC record on file — advice is blocked until KYC is completed."
    if kyc.kyc_status == KycStatus.OVERDUE:
        return (
            f"KYC expired on {kyc.expires_on} — renew before recommending any product."
        )
    if kyc.kyc_status == KycStatus.MISSING:
        return (
            "KYC documents outstanding ("
            + ", ".join(kyc.missing_documents)
            + ") — advice is blocked until they are received."
        )
    if kyc.suitability_expires_on and kyc.suitability_expires_on < as_of:
        return (
            f"Suitability assessment lapsed on {kyc.suitability_expires_on} — "
            "re-assess before recommending."
        )
    if view.client.mandate == Mandate.EXECUTION_ONLY:
        return (
            "Client is execution-only. Advice and recommendations are outside the "
            "agreed mandate."
        )
    return None


def gate_product(product: Product, view: ClientView) -> GateResult:
    """Per-product hard gates."""
    reasons = []
    client = view.client

    if RISK_RANK[product.risk_level] > RISK_RANK[client.risk_profile]:
        reasons.append(
            f"Product risk ({product.risk_level.value}) exceeds the client's "
            f"agreed profile ({client.risk_profile.value})."
        )

    permission = view.permission
    if permission is None:
        reasons.append("No permission record on file.")
    elif product.product_type not in permission.allowed_product_types:
        reasons.append(
            f"Client is not permissioned for {product.product_type.replace('_', ' ')}."
        )

    # Financing is a liability, not funded from investable cash, so the
    # affordability test does not apply to it.
    if product.product_type != "financing" and product.min_investment > 0:
        if client.investable_cash < product.min_investment:
            reasons.append(
                f"Minimum {product.min_investment:,.0f} THB exceeds investable cash of "
                f"{client.investable_cash:,.0f} THB (after the liquidity reserve)."
            )

    return GateResult(passed=not reasons, reasons=reasons)


# ---------------------------------------------------------------------------
# Scoring, among survivors only.
# ---------------------------------------------------------------------------


def _goal_match(product: Product, goals: list[GoalType]) -> float:
    if not goals:
        return 0.5
    hits = len(set(product.goals_addressed) & set(goals))
    return min(1.0, hits / len(goals)) if hits else 0.0


def _risk_fit(product: Product, client_profile: RiskProfile) -> float:
    """Closer to the client's ceiling is a better use of their risk budget."""
    gap = RISK_RANK[client_profile] - RISK_RANK[product.risk_level]
    return max(0.0, 1.0 - gap * 0.25)


def _horizon_fit(product: Product, horizon_years: Optional[float]) -> float:
    if horizon_years is None:
        return 0.5
    if product.horizon_years <= horizon_years:
        return 1.0
    overshoot = product.horizon_years - horizon_years
    return max(0.0, 1.0 - overshoot / 10.0)


def _affordability(product: Product, investable: float) -> float:
    if product.min_investment <= 0:
        return 1.0
    if investable <= 0:
        return 0.0
    headroom = investable / product.min_investment
    return min(1.0, headroom / 4.0)


def _liquidity_fit(product: Product, needs_liquidity: bool) -> float:
    if not needs_liquidity:
        return 1.0
    return 1.0 if product.liquidity_days <= 7 else 0.0


def score_product(
    product: Product,
    view: ClientView,
    goals: list[GoalType],
    horizon_years: Optional[float],
) -> tuple[float, list[str], list[str]]:
    client = view.client
    needs_liquidity = GoalType.LIQUIDITY in goals

    goal_match = _goal_match(product, goals)
    risk_fit = _risk_fit(product, client.risk_profile)
    horizon_fit = _horizon_fit(product, horizon_years)
    affordability = _affordability(product, client.investable_cash)
    liquidity_fit = _liquidity_fit(product, needs_liquidity)

    score = (
        goal_match * W_GOAL_MATCH
        + risk_fit * W_RISK_FIT
        + horizon_fit * W_HORIZON_FIT
        + affordability * W_AFFORDABILITY
        + liquidity_fit * W_LIQUIDITY_FIT
    )

    rationale, cautions = [], []
    matched = [g.value for g in product.goals_addressed if g in goals]
    if matched:
        rationale.append(f"Addresses the client's {', '.join(matched)} goal.")
    if risk_fit >= 0.75:
        rationale.append(
            f"Risk level ({product.risk_level.value}) sits within the client's "
            f"{client.risk_profile.value} profile."
        )
    if affordability >= 0.5:
        rationale.append(
            f"Minimum {product.min_investment:,.0f} THB is comfortably within "
            f"{client.investable_cash:,.0f} THB of investable cash."
        )
    if needs_liquidity and product.liquidity_days <= 7:
        rationale.append(f"Redeemable in {product.liquidity_days} day(s).")

    if product.liquidity_days > 365:
        cautions.append(
            f"Locked up for roughly {product.liquidity_days // 365} year(s) — "
            "confirm the client does not need these funds."
        )
    if horizon_years is not None and product.horizon_years > horizon_years:
        cautions.append(
            f"Product horizon ({product.horizon_years:g}y) is longer than the stated "
            f"need ({horizon_years:g}y)."
        )
    if product.product_type == "financing":
        cautions.append("Creates a liability. Rate shown is a cost to the client.")
    # Only worth flagging where there is real risk to be at the top of. On a
    # money-market fund it is technically true and practically noise.
    if (
        RISK_RANK[product.risk_level] == RISK_RANK[client.risk_profile]
        and RISK_RANK[product.risk_level] >= RISK_RANK[RiskProfile.BALANCED]
    ):
        cautions.append("Sits at the top of the client's risk tolerance.")

    return score, rationale, cautions


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def recommend(
    client_id: str,
    goals: Optional[list[GoalType]] = None,
    horizon_years: Optional[float] = None,
    limit: int = 5,
    gate: Optional[DataGate] = None,
) -> dict:
    gate = gate or get_gate()
    view = gate.client_view(client_id)
    if view is None:
        raise KeyError(f"unknown client: {client_id}")

    # If the RM named no goals, fall back to the client's confirmed goals.
    if not goals:
        goals = [g.goal_type for g in view.goals if g.confirmed_with_client]

    block = client_level_block(view, gate.as_of)
    catalog = load_catalog(gate)

    if block:
        # Everything is excluded for one reason. Say it once, loudly.
        return {
            "client_id": client_id,
            "client_name": view.client.name,
            "goals": [g.value for g in goals],
            "blocked": True,
            "block_reason": block,
            "recommended": [],
            "excluded": [ExcludedProduct(p, [block]).to_dict() for p in catalog],
            "context": _context(view),
        }

    recommended, excluded = [], []
    for product in catalog:
        result = gate_product(product, view)
        if not result.passed:
            excluded.append(ExcludedProduct(product, result.reasons))
            continue

        # Relevance is its own gate. A product that addresses none of the goals
        # is not a weak match to be ranked low — it is an answer to a question
        # nobody asked, and it must not appear at all.
        if goals and not set(product.goals_addressed) & set(goals):
            excluded.append(
                ExcludedProduct(
                    product,
                    [
                        "Does not address "
                        + " or ".join(g.value.replace("_", " ") for g in goals)
                        + "."
                    ],
                )
            )
            continue

        score, rationale, cautions = score_product(product, view, goals, horizon_years)
        recommended.append(Recommendation(product, score, rationale, cautions))

    recommended.sort(key=lambda r: -r.score)

    return {
        "client_id": client_id,
        "client_name": view.client.name,
        "goals": [g.value for g in goals],
        "blocked": False,
        "block_reason": None,
        "recommended": [r.to_dict() for r in recommended[:limit]],
        "excluded": [e.to_dict() for e in excluded],
        "context": _context(view),
    }


def _context(view: ClientView) -> dict:
    client = view.client
    return {
        "risk_profile": client.risk_profile.value,
        "mandate": client.mandate.value,
        "investable_cash": round(client.investable_cash, 2),
        "cash_balance": client.cash_balance,
        "liquidity_reserve_target": client.liquidity_reserve_target,
        "aum": client.aum,
        "kyc_status": view.kyc.kyc_status.value if view.kyc else "missing",
        "allowed_product_types": view.permission.allowed_product_types if view.permission else [],
        "confirmed_goals": [
            {"goal_type": g.goal_type.value, "label": g.label, "funded_ratio": round(g.funded_ratio, 3)}
            for g in view.goals
            if g.confirmed_with_client
        ],
    }
