"""Active / At-Risk Client module (Dashboard 3).

Answers "who has gone quiet, and is there money sitting idle while they do".
Activity is measured from the most recent *client-initiated* event — a deposit,
a withdrawal, or a trade. An RM's own outbound call does not make a client
active, so last_contact_on is reported but never used to compute the status.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

from data_gate.gate import DataGate, get_gate
from data_gate.models import ActivityStatus, ClientView

# Months since the last client-initiated event.
COOLING_AFTER_MONTHS = 6
DORMANT_AFTER_MONTHS = 12
INACTIVE_AFTER_MONTHS = 24

DAYS_PER_MONTH = 30.44


@dataclass
class ActivityRow:
    client_id: str
    client_name: str
    segment: str
    status: ActivityStatus
    months_since_activity: Optional[float]
    last_activity_on: Optional[date]
    last_activity_kind: Optional[str]
    last_deposit_on: Optional[date]
    last_withdrawal_on: Optional[date]
    last_trade_on: Optional[date]
    last_contact_on: Optional[date]
    idle_cash: float
    aum: float
    matured_value: float
    reengagement_reason: Optional[str]

    def to_dict(self) -> dict:
        def iso(d: Optional[date]) -> Optional[str]:
            return d.isoformat() if d else None

        return {
            "client_id": self.client_id,
            "client_name": self.client_name,
            "segment": self.segment,
            "status": self.status.value,
            "months_since_activity": (
                round(self.months_since_activity, 1)
                if self.months_since_activity is not None
                else None
            ),
            "last_activity_on": iso(self.last_activity_on),
            "last_activity_kind": self.last_activity_kind,
            "last_deposit_on": iso(self.last_deposit_on),
            "last_withdrawal_on": iso(self.last_withdrawal_on),
            "last_trade_on": iso(self.last_trade_on),
            "last_contact_on": iso(self.last_contact_on),
            "idle_cash": round(self.idle_cash, 2),
            "aum": self.aum,
            "matured_value": round(self.matured_value, 2),
            "reengagement_reason": self.reengagement_reason,
        }


def classify(months: Optional[float]) -> ActivityStatus:
    if months is None:
        return ActivityStatus.INACTIVE
    if months >= INACTIVE_AFTER_MONTHS:
        return ActivityStatus.INACTIVE
    if months >= DORMANT_AFTER_MONTHS:
        return ActivityStatus.DORMANT
    if months >= COOLING_AFTER_MONTHS:
        return ActivityStatus.COOLING
    return ActivityStatus.ACTIVE


def build_row(view: ClientView, as_of: date) -> ActivityRow:
    client = view.client

    events = {
        "deposit": client.last_deposit_on,
        "withdrawal": client.last_withdrawal_on,
        "trade": client.last_trade_on,
    }
    dated = {k: v for k, v in events.items() if v is not None}
    if dated:
        kind, last = max(dated.items(), key=lambda kv: kv[1])
        months = (as_of - last).days / DAYS_PER_MONTH
    else:
        kind, last, months = None, None, None

    status = classify(months)

    matured = sum(
        h.market_value
        for h in client.holdings
        if h.maturity_date is not None and h.maturity_date <= as_of
    )

    # Why it is worth calling now — the "early signal" the brief asks for.
    reason = None
    if status != ActivityStatus.ACTIVE:
        if matured > 0:
            reason = f"{matured:,.0f} THB matured and sitting uninvested"
        elif client.investable_cash >= 1_000_000:
            reason = f"{client.investable_cash:,.0f} THB idle above the liquidity reserve"
        elif status in (ActivityStatus.DORMANT, ActivityStatus.INACTIVE):
            reason = f"No client-initiated activity for {months:.0f} months"

    return ActivityRow(
        client_id=client.client_id,
        client_name=client.name,
        segment=client.segment,
        status=status,
        months_since_activity=months,
        last_activity_on=last,
        last_activity_kind=kind,
        last_deposit_on=client.last_deposit_on,
        last_withdrawal_on=client.last_withdrawal_on,
        last_trade_on=client.last_trade_on,
        last_contact_on=client.last_contact_on,
        idle_cash=client.investable_cash,
        aum=client.aum,
        matured_value=matured,
        reengagement_reason=reason,
    )


def build_activity_dashboard(
    rm_id: Optional[str] = None,
    status: Optional[ActivityStatus] = None,
    gate: Optional[DataGate] = None,
) -> dict:
    gate = gate or get_gate()
    rm_id = rm_id or gate.settings.rm_id

    rows = [build_row(v, gate.as_of) for v in gate.client_views(rm_id)]
    if status is not None:
        rows = [r for r in rows if r.status == status]

    # Quietest first, and among equals the ones with money going to waste.
    rows.sort(key=lambda r: (-(r.months_since_activity or 999), -r.idle_cash))

    by_status = {s.value: len([r for r in rows if r.status == s]) for s in ActivityStatus}
    at_risk = [r for r in rows if r.status in (ActivityStatus.DORMANT, ActivityStatus.INACTIVE)]

    return {
        "as_of": gate.as_of.isoformat(),
        "summary": {
            "total": len(rows),
            "by_status": by_status,
            "at_risk": len(at_risk),
            "idle_cash_at_risk": round(sum(r.idle_cash for r in at_risk), 2),
            "matured_at_risk": round(sum(r.matured_value for r in at_risk), 2),
        },
        "rows": [r.to_dict() for r in rows],
    }
