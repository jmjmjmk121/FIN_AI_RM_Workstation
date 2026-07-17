"""KYC module (Dashboard 4).

Replaces the manual expiry-date tracking the brief describes. Status is always
derived from the record's dates by the data gate, never read from a stored
label, so a stale batch cannot make an expired KYC look valid.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

from data_gate.gate import DataGate, get_gate
from data_gate.models import ClientView, KycStatus

# Renewal packs go out this far ahead of expiry.
RENEWAL_LEAD_DAYS = 60


@dataclass
class KycRow:
    client_id: str
    client_name: str
    segment: str
    status: KycStatus
    expires_on: Optional[date]
    days_to_expiry: Optional[int]
    last_review_on: Optional[date]
    aml_risk_rating: str
    missing_documents: list[str]
    suitability_expires_on: Optional[date]
    suitability_overdue: bool
    advice_blocked: bool
    action: str

    def to_dict(self) -> dict:
        def iso(d: Optional[date]) -> Optional[str]:
            return d.isoformat() if d else None

        return {
            "client_id": self.client_id,
            "client_name": self.client_name,
            "segment": self.segment,
            "status": self.status.value,
            "expires_on": iso(self.expires_on),
            "days_to_expiry": self.days_to_expiry,
            "last_review_on": iso(self.last_review_on),
            "aml_risk_rating": self.aml_risk_rating,
            "missing_documents": self.missing_documents,
            "suitability_expires_on": iso(self.suitability_expires_on),
            "suitability_overdue": self.suitability_overdue,
            "advice_blocked": self.advice_blocked,
            "action": self.action,
        }


def _action(status: KycStatus, days: Optional[int], missing: list[str], suit_overdue: bool) -> str:
    if status == KycStatus.MISSING and missing:
        return f"Chase outstanding documents: {', '.join(missing)}"
    if status == KycStatus.MISSING:
        return "Open a KYC file for this client"
    if status == KycStatus.OVERDUE:
        return f"Renew now — lapsed {abs(days)} days ago, advice is blocked"
    if status == KycStatus.DUE_SOON:
        return f"Send renewal pack — expires in {days} days"
    if suit_overdue:
        return "KYC valid, but re-run the suitability assessment"
    return "No action — next review scheduled"


def build_row(view: ClientView, as_of: date) -> KycRow:
    client = view.client
    kyc = view.kyc

    if kyc is None:
        return KycRow(
            client_id=client.client_id,
            client_name=client.name,
            segment=client.segment,
            status=KycStatus.MISSING,
            expires_on=None,
            days_to_expiry=None,
            last_review_on=None,
            aml_risk_rating="unknown",
            missing_documents=[],
            suitability_expires_on=None,
            suitability_overdue=False,
            advice_blocked=True,
            action="Open a KYC file for this client",
        )

    days = (kyc.expires_on - as_of).days if kyc.expires_on else None
    suit_overdue = bool(kyc.suitability_expires_on and kyc.suitability_expires_on < as_of)
    blocked = kyc.kyc_status in (KycStatus.OVERDUE, KycStatus.MISSING) or suit_overdue

    return KycRow(
        client_id=client.client_id,
        client_name=client.name,
        segment=client.segment,
        status=kyc.kyc_status,
        expires_on=kyc.expires_on,
        days_to_expiry=days,
        last_review_on=kyc.last_review_on,
        aml_risk_rating=kyc.aml_risk_rating,
        missing_documents=kyc.missing_documents,
        suitability_expires_on=kyc.suitability_expires_on,
        suitability_overdue=suit_overdue,
        advice_blocked=blocked,
        action=_action(kyc.kyc_status, days, kyc.missing_documents, suit_overdue),
    )


# Worst first: what blocks advice today outranks what expires next quarter.
STATUS_ORDER = {
    KycStatus.OVERDUE: 0,
    KycStatus.MISSING: 1,
    KycStatus.DUE_SOON: 2,
    KycStatus.VALID: 3,
}


def build_kyc_dashboard(
    rm_id: Optional[str] = None,
    status: Optional[KycStatus] = None,
    gate: Optional[DataGate] = None,
) -> dict:
    gate = gate or get_gate()
    rm_id = rm_id or gate.settings.rm_id

    rows = [build_row(v, gate.as_of) for v in gate.client_views(rm_id)]
    if status is not None:
        rows = [r for r in rows if r.status == status]

    rows.sort(key=lambda r: (STATUS_ORDER[r.status], r.days_to_expiry if r.days_to_expiry is not None else 9999))

    by_status = {s.value: len([r for r in rows if r.status == s]) for s in KycStatus}
    renewals = [
        r for r in rows
        if r.days_to_expiry is not None and 0 <= r.days_to_expiry <= RENEWAL_LEAD_DAYS
    ]

    return {
        "as_of": gate.as_of.isoformat(),
        "summary": {
            "total": len(rows),
            "by_status": by_status,
            "advice_blocked": len([r for r in rows if r.advice_blocked]),
            "renewals_due_60d": len(renewals),
            "suitability_overdue": len([r for r in rows if r.suitability_overdue]),
            "high_aml_risk": len([r for r in rows if r.aml_risk_rating == "high"]),
        },
        "rows": [r.to_dict() for r in rows],
    }
