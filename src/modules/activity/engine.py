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
    investment_activity: str
    relationship_activity: str
    permitted_action: str

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
            "investment_activity": self.investment_activity,
            "relationship_activity": self.relationship_activity,
            "permitted_action": self.permitted_action,
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


def _months_between(as_of: date, event_on: Optional[date]) -> Optional[float]:
    return (as_of - event_on).days / DAYS_PER_MONTH if event_on else None


def _investment_activity(client, as_of: date) -> str:
    """Investment behaviour and relationship engagement are different axes.

    A holding-only client is not labelled churn merely because there was no
    recent trade. Full reactivation detection needs event history and therefore
    remains deliberately absent until a bank CRM/transaction adapter exists.
    """
    trade_months = _months_between(as_of, client.last_trade_on)
    cash_dates = [d for d in (client.last_deposit_on, client.last_withdrawal_on) if d]
    cash_months = _months_between(as_of, max(cash_dates)) if cash_dates else None
    if trade_months is not None and trade_months < COOLING_AFTER_MONTHS:
        return "active_trading"
    if cash_months is not None and cash_months < COOLING_AFTER_MONTHS:
        return "active_cash_flow"
    if client.holdings:
        return "holding_only"
    return "no_recent_investment_activity"


def _relationship_activity(client, as_of: date) -> str:
    contact_months = _months_between(as_of, client.last_contact_on)
    if contact_months is None or contact_months >= 3:
        return "contact_silent"
    if contact_months >= 1:
        return "contact_cooling"
    return "recent_contact"


def _permitted_action(view: ClientView, status: ActivityStatus, as_of: date) -> str:
    permission = view.permission
    if permission is None or not permission.can_contact:
        return "DO_NOT_CONTACT"
    if permission.do_not_disturb_until and permission.do_not_disturb_until >= as_of:
        return "CHECK_CONTACT_LOCK"
    if view.kyc is None or view.kyc.kyc_status.value in {"overdue", "missing"}:
        return "CONFIRM_DATA"
    if status in {ActivityStatus.DORMANT, ActivityStatus.INACTIVE}:
        return "REVIEW_BEFORE_REENGAGE"
    return "REVIEW_NEXT_NEED"


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

    # Why it may deserve review now. An alert is not permission to call or sell.
    reason = None
    if status != ActivityStatus.ACTIVE:
        if matured > 0:
            reason = f"มีสินทรัพย์ครบกำหนด {matured:,.0f} บาท ควรตรวจความต้องการก่อนติดต่อ"
        elif client.investable_cash >= 1_000_000:
            reason = f"มีเงินสดเหนือเงินสำรอง {client.investable_cash:,.0f} บาท ควรยืนยันเป้าหมายก่อนเสนอทางเลือก"
        elif status in (ActivityStatus.DORMANT, ActivityStatus.INACTIVE):
            reason = f"ไม่มีกิจกรรมที่ลูกค้าเป็นผู้เริ่มประมาณ {months:.0f} เดือน"

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
        investment_activity=_investment_activity(client, as_of),
        relationship_activity=_relationship_activity(client, as_of),
        permitted_action=_permitted_action(view, status, as_of),
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
    investment_states = {
        key: len([r for r in rows if r.investment_activity == key])
        for key in (
            "active_trading", "active_cash_flow", "holding_only",
            "no_recent_investment_activity",
        )
    }
    relationship_states = {
        key: len([r for r in rows if r.relationship_activity == key])
        for key in ("recent_contact", "contact_cooling", "contact_silent")
    }
    at_risk = [r for r in rows if r.status in (ActivityStatus.DORMANT, ActivityStatus.INACTIVE)]

    return {
        "as_of": gate.as_of.isoformat(),
        "summary": {
            "total": len(rows),
            "by_status": by_status,
            "by_investment_activity": investment_states,
            "by_relationship_activity": relationship_states,
            "at_risk": len(at_risk),
            "idle_cash_at_risk": round(sum(r.idle_cash for r in at_risk), 2),
            "matured_at_risk": round(sum(r.matured_value for r in at_risk), 2),
        },
        "rows": [r.to_dict() for r in rows],
    }
