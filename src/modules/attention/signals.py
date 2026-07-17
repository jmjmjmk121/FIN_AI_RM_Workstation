"""Signal detectors for the Attention & Channel module.

Each detector answers one question about one client and returns a Signal with
the evidence that fired it. Detectors never rank and never decide a lane — they
only report what is true. Lane assignment and gating live in engine.py, so the
rule "care outranks growth" is enforced in exactly one place.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Optional

from data_gate.models import (
    RISK_RANK,
    ClientView,
    GoalType,
    KycStatus,
    Lane,
    Mandate,
    RiskProfile,
)

# A single position above this share of AUM is a severe concentration.
CONCENTRATION_THRESHOLD = 0.35
# A critical goal below this funded ratio, with the clock running out, is at risk.
GOAL_AT_RISK_RATIO = 0.60
GOAL_AT_RISK_YEARS = 5
# Cash above the reserve below this is not worth an outreach.
MATERIAL_EXCESS_CASH = 1_000_000.0
# Instruments maturing inside this window need a reinvestment conversation.
MATURITY_WINDOW_DAYS = 60
# Protection goals are a growth need only when the gap is real.
PROTECTION_GAP_RATIO = 0.70


@dataclass
class Signal:
    code: str
    lane: Lane
    title: str
    detail: str
    # 1-5, 5 = most severe. Drives ordering within a lane.
    severity: int
    evidence: dict = field(default_factory=dict)
    # Days until this becomes a breach. None = no clock.
    days_to_deadline: Optional[int] = None
    # Care signals that are mandatory suppress the growth lane entirely.
    mandatory: bool = False


Detector = Callable[[ClientView, date], list[Signal]]

# ---------------------------------------------------------------------------
# Care lane — mandatory. These exist to protect the client.
# ---------------------------------------------------------------------------


def detect_kyc(view: ClientView, as_of: date) -> list[Signal]:
    kyc = view.kyc
    if kyc is None:
        return [
            Signal(
                code="KYC_MISSING",
                lane=Lane.CARE,
                title="KYC record missing",
                detail="No KYC record on file. Client cannot be advised until resolved.",
                severity=5,
                mandatory=True,
            )
        ]

    signals = []
    if kyc.kyc_status == KycStatus.OVERDUE:
        days_over = (as_of - kyc.expires_on).days if kyc.expires_on else 0
        signals.append(
            Signal(
                code="KYC_OVERDUE",
                lane=Lane.CARE,
                title=f"KYC expired {days_over} days ago",
                detail=f"KYC lapsed on {kyc.expires_on}. Renewal required before further advice.",
                severity=5,
                evidence={"expires_on": str(kyc.expires_on), "days_overdue": days_over},
                days_to_deadline=-days_over,
                mandatory=True,
            )
        )
    elif kyc.kyc_status == KycStatus.DUE_SOON:
        days_left = (kyc.expires_on - as_of).days
        signals.append(
            Signal(
                code="KYC_DUE_SOON",
                lane=Lane.CARE,
                title=f"KYC expires in {days_left} days",
                detail=f"KYC due for renewal on {kyc.expires_on}. Start the renewal now.",
                severity=3 if days_left > 30 else 4,
                evidence={"expires_on": str(kyc.expires_on), "days_left": days_left},
                days_to_deadline=days_left,
                mandatory=True,
            )
        )
    elif kyc.kyc_status == KycStatus.MISSING:
        signals.append(
            Signal(
                code="KYC_DOCUMENTS_MISSING",
                lane=Lane.CARE,
                title="KYC documents outstanding",
                detail="Outstanding: " + ", ".join(kyc.missing_documents),
                severity=4,
                evidence={"missing_documents": kyc.missing_documents},
                mandatory=True,
            )
        )

    if kyc.suitability_expires_on and kyc.suitability_expires_on < as_of:
        days_over = (as_of - kyc.suitability_expires_on).days
        signals.append(
            Signal(
                code="SUITABILITY_REVIEW_OVERDUE",
                lane=Lane.CARE,
                title=f"Suitability review {days_over} days overdue",
                detail=(
                    f"Suitability assessment lapsed on {kyc.suitability_expires_on}. "
                    "Re-assess before any recommendation."
                ),
                severity=4,
                evidence={"suitability_expires_on": str(kyc.suitability_expires_on)},
                days_to_deadline=-days_over,
                mandatory=True,
            )
        )
    return signals


def detect_suitability_conflict(view: ClientView, as_of: date) -> list[Signal]:
    """Holdings riskier than the client's agreed profile."""
    client = view.client
    ceiling = RISK_RANK[client.risk_profile]
    breaches = [
        h for h in client.holdings if RISK_RANK[h.risk_level] > ceiling
    ]
    if not breaches:
        return []

    exposure = sum(h.market_value for h in breaches)
    share = exposure / client.aum if client.aum else 0.0
    return [
        Signal(
            code="SUITABILITY_CONFLICT",
            lane=Lane.CARE,
            title=f"{len(breaches)} holding(s) above agreed risk profile",
            detail=(
                f"{', '.join(h.symbol for h in breaches)} exceed a "
                f"{client.risk_profile.value} profile — "
                f"{share:.0%} of portfolio ({exposure:,.0f} THB)."
            ),
            severity=5 if share > 0.25 else 4,
            evidence={
                "symbols": [h.symbol for h in breaches],
                "exposure": round(exposure, 2),
                "share_of_aum": round(share, 4),
                "client_profile": client.risk_profile.value,
            },
            mandatory=True,
        )
    ]


def detect_liquidity_shortfall(view: ClientView, as_of: date) -> list[Signal]:
    client = view.client
    gap = client.liquidity_gap
    if gap <= 0:
        return []
    coverage = client.cash_balance / client.liquidity_reserve_target if client.liquidity_reserve_target else 1.0
    return [
        Signal(
            code="LIQUIDITY_SHORTFALL",
            lane=Lane.CARE,
            title=f"Liquidity reserve short by {gap:,.0f} THB",
            detail=(
                f"Cash {client.cash_balance:,.0f} against an agreed reserve of "
                f"{client.liquidity_reserve_target:,.0f} ({coverage:.0%} covered)."
            ),
            severity=5 if coverage < 0.5 else 3,
            evidence={
                "cash_balance": client.cash_balance,
                "reserve_target": client.liquidity_reserve_target,
                "gap": round(gap, 2),
                "coverage": round(coverage, 4),
            },
            mandatory=True,
        )
    ]


def detect_concentration(view: ClientView, as_of: date) -> list[Signal]:
    client = view.client
    if not client.aum:
        return []
    signals = []
    for holding in client.holdings:
        share = holding.market_value / client.aum
        if share >= CONCENTRATION_THRESHOLD:
            signals.append(
                Signal(
                    code="SEVERE_CONCENTRATION",
                    lane=Lane.CARE,
                    title=f"{holding.symbol} is {share:.0%} of portfolio",
                    detail=(
                        f"Single-name exposure of {holding.market_value:,.0f} THB "
                        f"({share:.0%}) exceeds the {CONCENTRATION_THRESHOLD:.0%} threshold."
                    ),
                    severity=5 if share >= 0.5 else 4,
                    evidence={
                        "symbol": holding.symbol,
                        "market_value": holding.market_value,
                        "share_of_aum": round(share, 4),
                    },
                    mandatory=True,
                )
            )
    return signals


def detect_critical_goal_at_risk(view: ClientView, as_of: date) -> list[Signal]:
    signals = []
    for goal in view.goals:
        if goal.priority > 2:
            continue
        years_left = (goal.target_date - as_of).days / 365.25
        if goal.funded_ratio >= GOAL_AT_RISK_RATIO or years_left > GOAL_AT_RISK_YEARS:
            continue
        signals.append(
            Signal(
                code="CRITICAL_GOAL_AT_RISK",
                lane=Lane.CARE,
                title=f"{goal.label} is {goal.funded_ratio:.0%} funded",
                detail=(
                    f"Target {goal.target_amount:,.0f} THB by {goal.target_date} "
                    f"({years_left:.1f} years away), funded {goal.funded_amount:,.0f}."
                ),
                severity=5 if goal.priority == 1 and years_left < 2 else 4,
                evidence={
                    "goal_id": goal.goal_id,
                    "funded_ratio": round(goal.funded_ratio, 4),
                    "target_date": str(goal.target_date),
                    "shortfall": round(goal.target_amount - goal.funded_amount, 2),
                },
                days_to_deadline=(goal.target_date - as_of).days,
                mandatory=True,
            )
        )
    return signals


def detect_vulnerable_client(view: ClientView, as_of: date) -> list[Signal]:
    client = view.client
    if not client.is_vulnerable:
        return []
    return [
        Signal(
            code="VULNERABLE_CLIENT_NEED",
            lane=Lane.CARE,
            title="Vulnerable client — enhanced care",
            detail=client.vulnerability_note or "Flagged as vulnerable. Apply enhanced care standards.",
            severity=4,
            evidence={"note": client.vulnerability_note},
            mandatory=True,
        )
    ]


def detect_service_issue(view: ClientView, as_of: date) -> list[Signal]:
    signals = []
    for issue in view.client.service_issues:
        if issue.resolved:
            continue
        age = (as_of - issue.opened_on).days
        signals.append(
            Signal(
                code="UNRESOLVED_SERVICE_ISSUE",
                lane=Lane.CARE,
                title=f"Open service issue ({age} days)",
                detail=issue.summary,
                severity=min(5, issue.severity + (1 if age > 30 else 0)),
                evidence={"issue_id": issue.issue_id, "age_days": age},
                mandatory=True,
            )
        )
    return signals


# ---------------------------------------------------------------------------
# Growth lane — only fires on a confirmed or strongly evidenced need.
# ---------------------------------------------------------------------------


def detect_excess_liquidity(view: ClientView, as_of: date) -> list[Signal]:
    """Investable cash *after* the liquidity reserve is honoured."""
    client = view.client
    investable = client.investable_cash
    if investable < MATERIAL_EXCESS_CASH:
        return []
    return [
        Signal(
            code="EXCESS_LIQUIDITY",
            lane=Lane.GROWTH,
            title=f"{investable:,.0f} THB investable after reserve",
            detail=(
                f"Cash {client.cash_balance:,.0f} less reserve "
                f"{client.liquidity_reserve_target:,.0f} leaves {investable:,.0f} idle."
            ),
            severity=3 if investable > 10_000_000 else 2,
            evidence={
                "investable_cash": round(investable, 2),
                "cash_balance": client.cash_balance,
                "reserve_target": client.liquidity_reserve_target,
            },
        )
    ]


def detect_maturing_instrument(view: ClientView, as_of: date) -> list[Signal]:
    signals = []
    for holding in view.client.holdings:
        if holding.maturity_date is None:
            continue
        days = (holding.maturity_date - as_of).days
        if days > MATURITY_WINDOW_DAYS:
            continue
        matured = days < 0
        signals.append(
            Signal(
                code="MATURED_INVESTMENT" if matured else "MATURING_INVESTMENT",
                lane=Lane.GROWTH,
                title=(
                    f"{holding.symbol} matured {abs(days)} days ago"
                    if matured
                    else f"{holding.symbol} matures in {days} days"
                ),
                detail=(
                    f"{holding.market_value:,.0f} THB "
                    f"{'sitting uninvested since' if matured else 'due for reinvestment on'} "
                    f"{holding.maturity_date}."
                ),
                severity=3 if matured else 2,
                evidence={
                    "symbol": holding.symbol,
                    "market_value": holding.market_value,
                    "maturity_date": str(holding.maturity_date),
                },
                days_to_deadline=days,
            )
        )
    return signals


def detect_planning_needs(view: ClientView, as_of: date) -> list[Signal]:
    """Goal-driven growth needs.

    Only confirmed goals qualify. An unconfirmed goal is a hypothesis, and the
    spec asks for confirmed or strongly evidenced need — so it does not fire.
    """
    signals = []
    for goal in view.goals:
        if not goal.confirmed_with_client:
            continue
        years_left = (goal.target_date - as_of).days / 365.25

        if goal.goal_type == GoalType.RETIREMENT and goal.funded_ratio < 0.9:
            signals.append(
                Signal(
                    code="RETIREMENT_PLANNING_NEED",
                    lane=Lane.GROWTH,
                    title=f"Retirement plan {goal.funded_ratio:.0%} funded",
                    detail=(
                        f"Confirmed retirement goal of {goal.target_amount:,.0f} THB by "
                        f"{goal.target_date}, {years_left:.1f} years out."
                    ),
                    severity=3 if years_left < 10 else 2,
                    evidence={"goal_id": goal.goal_id, "funded_ratio": round(goal.funded_ratio, 4)},
                    days_to_deadline=(goal.target_date - as_of).days,
                )
            )
        elif goal.goal_type == GoalType.PROTECTION and goal.funded_ratio < PROTECTION_GAP_RATIO:
            gap = goal.target_amount - goal.funded_amount
            signals.append(
                Signal(
                    code="PROTECTION_GAP",
                    lane=Lane.GROWTH,
                    title=f"Protection gap of {gap:,.0f} THB",
                    detail=f"Confirmed protection goal only {goal.funded_ratio:.0%} covered.",
                    severity=3,
                    evidence={"goal_id": goal.goal_id, "gap": round(gap, 2)},
                )
            )
        elif goal.goal_type == GoalType.FINANCING and goal.funded_ratio < 1.0:
            signals.append(
                Signal(
                    code="FINANCING_NEED",
                    lane=Lane.GROWTH,
                    title=goal.label,
                    detail=(
                        f"Confirmed financing need of {goal.target_amount:,.0f} THB "
                        f"by {goal.target_date}."
                    ),
                    severity=2,
                    evidence={"goal_id": goal.goal_id},
                    days_to_deadline=(goal.target_date - as_of).days,
                )
            )
        elif goal.goal_type == GoalType.TAX and years_left <= 1:
            signals.append(
                Signal(
                    code="TAX_EVENT",
                    lane=Lane.GROWTH,
                    title="Tax-year allocation window",
                    detail=f"Confirmed tax goal closing {goal.target_date}.",
                    severity=3,
                    evidence={"goal_id": goal.goal_id},
                    days_to_deadline=(goal.target_date - as_of).days,
                )
            )
    return signals


CARE_DETECTORS: list[Detector] = [
    detect_kyc,
    detect_suitability_conflict,
    detect_liquidity_shortfall,
    detect_concentration,
    detect_critical_goal_at_risk,
    detect_vulnerable_client,
    detect_service_issue,
]

GROWTH_DETECTORS: list[Detector] = [
    detect_excess_liquidity,
    detect_maturing_instrument,
    detect_planning_needs,
]
