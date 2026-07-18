"""The data gate.

Every module reads through here — never from a source directly. The gate:
  - loads and joins the sources into one ClientView per client,
  - recomputes KYC status from dates rather than trusting the stored label,
  - answers "may we contact this client at all" before any module ranks anything,
  - keeps market data behind one provider with a visible source/degrade flag.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from typing import Optional

from .config import Settings, get_settings
from .models import Client, ClientView, EodPrice, Goal, KycRecord, KycStatus, Permission, ProductRecord
from .sources.mock_sources import (
    Client360Source,
    GoalLedgerSource,
    KycCrmSource,
    PermissionSource,
    ProductCatalogSource,
)
from .sources.setsmart import EodResult, SetsmartListedProvider

# KYC inside this window is "due soon" rather than merely valid.
KYC_DUE_SOON_DAYS = 60


@dataclass
class ContactDecision:
    """Whether the RM may contact this client, and why not if not.

    This is a hard gate, checked before prioritisation. A client we may not
    contact must not occupy a slot on the RM's day.
    """

    allowed: bool
    reason: Optional[str] = None


def resolve_kyc_status(kyc: Optional[KycRecord], as_of: date) -> KycStatus:
    """Derive KYC status from the record's dates.

    The stored label is treated as a hint only — a stale nightly batch must not
    be able to make an expired KYC look valid.
    """
    if kyc is None:
        return KycStatus.MISSING
    if kyc.missing_documents:
        return KycStatus.MISSING
    if kyc.expires_on is None:
        return KycStatus.MISSING
    if kyc.expires_on < as_of:
        return KycStatus.OVERDUE
    if (kyc.expires_on - as_of).days <= KYC_DUE_SOON_DAYS:
        return KycStatus.DUE_SOON
    return KycStatus.VALID


class DataGate:
    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()
        self._clients = Client360Source()
        self._goals = GoalLedgerSource()
        self._kyc = KycCrmSource()
        self._permissions = PermissionSource()
        self._products = ProductCatalogSource()
        self.market = SetsmartListedProvider(self.settings)

    @property
    def as_of(self) -> date:
        return self.settings.as_of

    # ---- assembly -----------------------------------------------------

    def client_views(self, rm_id: Optional[str] = None) -> list[ClientView]:
        """All clients for an RM, each joined with goals, KYC, and permission."""
        clients = self._clients.load()
        if rm_id:
            clients = [c for c in clients if c.rm_id == rm_id]

        goals_by_client: dict[str, list[Goal]] = {}
        for goal in self._goals.load():
            goals_by_client.setdefault(goal.client_id, []).append(goal)

        kyc_by_client = {k.client_id: k for k in self._kyc.load()}
        perm_by_client = {p.client_id: p for p in self._permissions.load()}

        views = []
        for client in clients:
            kyc = kyc_by_client.get(client.client_id)
            if kyc is not None:
                # Normalise here so no module has to re-derive it.
                kyc = kyc.model_copy(
                    update={"kyc_status": resolve_kyc_status(kyc, self.as_of)}
                )
            views.append(
                ClientView(
                    client=client,
                    goals=goals_by_client.get(client.client_id, []),
                    kyc=kyc,
                    permission=perm_by_client.get(client.client_id),
                )
            )
        return views

    def client_view(self, client_id: str) -> Optional[ClientView]:
        for view in self.client_views():
            if view.client.client_id == client_id:
                return view
        return None

    def products(self) -> list[ProductRecord]:
        """The governed product catalogue; modules never read fixture files."""
        return self._products.load()

    # ---- permission gate ----------------------------------------------

    def contact_decision(self, view: ClientView) -> ContactDecision:
        """Hard permission check. Runs before any prioritisation."""
        permission = view.permission
        if permission is None:
            return ContactDecision(False, "No permission record on file")
        if not permission.can_contact:
            return ContactDecision(False, "Client has withdrawn contact consent")
        if permission.do_not_disturb_until and permission.do_not_disturb_until >= self.as_of:
            return ContactDecision(
                False,
                f"Do-not-disturb until {permission.do_not_disturb_until.isoformat()}",
            )
        return ContactDecision(True)

    # ---- market data ---------------------------------------------------

    def eod_prices(self, security_type: str = "All") -> EodResult:
        return self.market.eod_by_security_type(security_type)

    def price_map(self) -> dict[str, EodPrice]:
        return {row.symbol: row for row in self.eod_prices().rows}

    def health(self) -> dict:
        result = self.eod_prices()
        return {
            "as_of": self.as_of.isoformat(),
            "sources": {
                "client_360": "fixture",
                "goal_ledger": "fixture",
                "kyc_crm": "fixture",
                "permission": "fixture",
                "product_catalog": "fixture",
                "setsmart_listed_eod": result.source,
            },
            "market": result.meta(),
            "config": self.settings.public_status(),
        }


@lru_cache
def get_gate() -> DataGate:
    return DataGate()
