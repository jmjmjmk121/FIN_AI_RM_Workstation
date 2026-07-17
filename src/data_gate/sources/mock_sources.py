"""Mock adapters for Client 360, Goal Ledger, and KYC/CRM.

Each adapter is the seam a real system slots into: swap the body of `load()`
for a real client and nothing downstream changes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from ..config import FIXTURE_DIR
from ..models import Client, Goal, KycRecord, Permission

T = TypeVar("T", bound=BaseModel)


def _load(path: Path, model: type[T]) -> list[T]:
    if not path.exists():
        raise FileNotFoundError(
            f"fixture {path.name} is missing — run: .venv/bin/python tools/generate_fixtures.py"
        )
    return [model.model_validate(row) for row in json.loads(path.read_text())]


class Client360Source:
    """Client 360 — holdings, cash, activity recency, vulnerability flags."""

    name = "client_360"

    def load(self) -> list[Client]:
        return _load(FIXTURE_DIR / "clients.json", Client)


class GoalLedgerSource:
    """Goal Ledger — client goals, targets, funding progress."""

    name = "goal_ledger"

    def load(self) -> list[Goal]:
        return _load(FIXTURE_DIR / "goals.json", Goal)


class KycCrmSource:
    """KYC / CRM — review dates, AML rating, outstanding documents."""

    name = "kyc_crm"

    def load(self) -> list[KycRecord]:
        return _load(FIXTURE_DIR / "kyc.json", KycRecord)


class PermissionSource:
    """Permission / mandate — contact consent and product entitlements."""

    name = "permission"

    def load(self) -> list[Permission]:
        return _load(FIXTURE_DIR / "permissions.json", Permission)
