"""Domain models shared across the data gate and every module.

These are the only shapes modules are allowed to see. Sources normalise into
these; modules never touch a raw source payload.
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class RiskProfile(str, Enum):
    """Client suitability band, ascending. Ordering is meaningful."""

    CONSERVATIVE = "conservative"
    MODERATE = "moderate"
    BALANCED = "balanced"
    GROWTH = "growth"
    AGGRESSIVE = "aggressive"


RISK_RANK: dict[RiskProfile, int] = {
    RiskProfile.CONSERVATIVE: 1,
    RiskProfile.MODERATE: 2,
    RiskProfile.BALANCED: 3,
    RiskProfile.GROWTH: 4,
    RiskProfile.AGGRESSIVE: 5,
}


class Mandate(str, Enum):
    EXECUTION_ONLY = "execution_only"
    ADVISORY = "advisory"
    DISCRETIONARY = "discretionary"


class GoalType(str, Enum):
    RETIREMENT = "retirement"
    EDUCATION = "education"
    PROTECTION = "protection"
    LIQUIDITY = "liquidity"
    WEALTH_TRANSFER = "wealth_transfer"
    FINANCING = "financing"
    TAX = "tax"


class KycStatus(str, Enum):
    VALID = "valid"
    DUE_SOON = "due_soon"
    OVERDUE = "overdue"
    MISSING = "missing"


class ActivityStatus(str, Enum):
    ACTIVE = "active"
    COOLING = "cooling"
    DORMANT = "dormant"
    INACTIVE = "inactive"


class Lane(str, Enum):
    CARE = "care"
    GROWTH = "growth"


class Holding(BaseModel):
    symbol: str
    security_type: str
    units: float
    cost_basis: float
    market_value: float
    asset_class: str
    risk_level: RiskProfile
    maturity_date: Optional[date] = None


class ServiceIssue(BaseModel):
    issue_id: str
    opened_on: date
    summary: str
    severity: int = Field(ge=1, le=5)
    resolved: bool = False


class Client(BaseModel):
    """Client 360 record."""

    client_id: str
    name: str
    rm_id: str
    segment: str
    date_of_birth: date
    risk_profile: RiskProfile
    suitability_reviewed_on: Optional[date] = None
    mandate: Mandate
    aum: float
    cash_balance: float
    liquidity_reserve_target: float
    holdings: list[Holding] = []
    service_issues: list[ServiceIssue] = []

    # Vulnerability is a compliance flag, not an inference.
    is_vulnerable: bool = False
    vulnerability_note: Optional[str] = None

    last_contact_on: Optional[date] = None
    last_deposit_on: Optional[date] = None
    last_withdrawal_on: Optional[date] = None
    last_trade_on: Optional[date] = None

    @property
    def investable_cash(self) -> float:
        """Cash above the client's agreed liquidity reserve. Never negative."""
        return max(0.0, self.cash_balance - self.liquidity_reserve_target)

    @property
    def liquidity_gap(self) -> float:
        """Shortfall against the agreed reserve. Never negative."""
        return max(0.0, self.liquidity_reserve_target - self.cash_balance)


class Goal(BaseModel):
    """Goal Ledger record."""

    goal_id: str
    client_id: str
    goal_type: GoalType
    label: str
    target_amount: float
    target_date: date
    funded_amount: float
    # 1 = critical. Drives the "critical goal at risk" care gate.
    priority: int = Field(ge=1, le=5)
    confirmed_with_client: bool = False

    @property
    def funded_ratio(self) -> float:
        if self.target_amount <= 0:
            return 1.0
        return self.funded_amount / self.target_amount


class KycRecord(BaseModel):
    """KYC / CRM compliance record."""

    client_id: str
    kyc_status: KycStatus
    last_review_on: Optional[date] = None
    expires_on: Optional[date] = None
    aml_risk_rating: str
    missing_documents: list[str] = []
    suitability_expires_on: Optional[date] = None


class Permission(BaseModel):
    """Permission / mandate record. The gate reads this before anything else."""

    client_id: str
    can_contact: bool = True
    marketing_consent: bool = False
    allowed_product_types: list[str] = []
    do_not_disturb_until: Optional[date] = None


class EodPrice(BaseModel):
    """One SETSMART Listed-company EOD row, normalised.

    `nav` is only populated for listed UT/ETF where the contract defines bvps
    as NAV. It is not a total-return figure.
    """

    date: date
    symbol: str
    security_type: str
    close: Optional[float] = None
    prior: Optional[float] = None
    pe: Optional[float] = None
    pbv: Optional[float] = None
    bvps: Optional[float] = None
    dividend_yield: Optional[float] = None
    market_cap: Optional[float] = None
    nav: Optional[float] = None
    source: str = "fixture"

    @property
    def change_pct(self) -> Optional[float]:
        if self.close is None or not self.prior:
            return None
        return (self.close - self.prior) / self.prior * 100.0


class ClientView(BaseModel):
    """Everything the modules need about one client, assembled by the gate."""

    client: Client
    goals: list[Goal] = []
    kyc: Optional[KycRecord] = None
    permission: Optional[Permission] = None
