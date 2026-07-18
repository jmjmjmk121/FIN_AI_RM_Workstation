"""Tests for the rule the brief cares most about:

    Business value cannot override mandatory care, suitability, or
    client-benefit gates.
"""

from datetime import date, timedelta

import pytest

from data_gate.gate import DataGate, resolve_kyc_status
from data_gate.models import (
    Client,
    ClientView,
    Goal,
    GoalType,
    Holding,
    KycRecord,
    KycStatus,
    Lane,
    Mandate,
    Permission,
    RiskProfile,
)
from modules.attention.engine import build_attention_list, build_daily_review_queue, evaluate_client

AS_OF = date(2026, 7, 17)


def make_client(**overrides) -> Client:
    base = dict(
        client_id="C9001",
        name="Test Client",
        rm_id="RM001",
        segment="Private",
        date_of_birth=date(1970, 1, 1),
        risk_profile=RiskProfile.BALANCED,
        mandate=Mandate.ADVISORY,
        aum=10_000_000.0,
        cash_balance=5_000_000.0,
        liquidity_reserve_target=1_000_000.0,
        holdings=[],
        service_issues=[],
    )
    base.update(overrides)
    return Client(**base)


def make_view(client=None, goals=None, kyc=None, permission=None) -> ClientView:
    client = client or make_client()
    if kyc is None:
        kyc = KycRecord(
            client_id=client.client_id,
            kyc_status=KycStatus.VALID,
            expires_on=AS_OF + timedelta(days=365),
            aml_risk_rating="low",
            suitability_expires_on=AS_OF + timedelta(days=365),
        )
    if permission is None:
        permission = Permission(client_id=client.client_id, can_contact=True)
    return ClientView(client=client, goals=goals or [], kyc=kyc, permission=permission)


@pytest.fixture
def gate():
    return DataGate()


# ---- KYC status is derived, not trusted -----------------------------------


def test_expired_kyc_is_overdue_even_if_record_says_valid():
    kyc = KycRecord(
        client_id="C1",
        kyc_status=KycStatus.VALID,  # stale label from an upstream batch
        expires_on=AS_OF - timedelta(days=1),
        aml_risk_rating="low",
    )
    assert resolve_kyc_status(kyc, AS_OF) == KycStatus.OVERDUE


def test_missing_documents_beat_a_valid_expiry_date():
    kyc = KycRecord(
        client_id="C1",
        kyc_status=KycStatus.VALID,
        expires_on=AS_OF + timedelta(days=365),
        aml_risk_rating="low",
        missing_documents=["Proof of address"],
    )
    assert resolve_kyc_status(kyc, AS_OF) == KycStatus.MISSING


# ---- the governing rule ---------------------------------------------------


def test_care_gate_suppresses_growth_for_a_high_value_client(gate):
    """A huge idle-cash opportunity must not outrank an expired KYC."""
    client = make_client(
        cash_balance=90_000_000.0,   # enormous growth opportunity
        liquidity_reserve_target=1_000_000.0,
        aum=400_000_000.0,
    )
    kyc = KycRecord(
        client_id=client.client_id,
        kyc_status=KycStatus.OVERDUE,
        expires_on=AS_OF - timedelta(days=30),
        aml_risk_rating="low",
        suitability_expires_on=AS_OF + timedelta(days=100),
    )
    item = evaluate_client(make_view(client=client, kyc=kyc), AS_OF, gate)

    assert item.lane == Lane.CARE
    assert any(s.code == "KYC_OVERDUE" for s in item.signals)
    # The opportunity is visible but set aside — not scoring, not driving lane.
    assert any(s.code == "EXCESS_LIQUIDITY" for s in item.suppressed_growth)
    assert not any(s.lane == Lane.GROWTH for s in item.signals)


def test_growth_lane_only_when_no_care_gate_is_open(gate):
    client = make_client(cash_balance=20_000_000.0, liquidity_reserve_target=1_000_000.0)
    item = evaluate_client(make_view(client=client), AS_OF, gate)

    assert item.lane == Lane.GROWTH
    assert item.suppressed_growth == []


def test_every_care_item_outranks_every_growth_item(gate):
    """Lane ordering must be total, not merely a tiebreak."""
    items = build_attention_list(gate=gate)
    lanes = [i.lane for i in items if i.contact_allowed]
    first_growth = next((n for n, l in enumerate(lanes) if l == Lane.GROWTH), None)
    if first_growth is not None:
        assert Lane.CARE not in lanes[first_growth:]


def test_daily_review_queue_is_bounded_and_keeps_care_first(gate):
    items = build_attention_list(gate=gate)
    queue = build_daily_review_queue(items, limit=48, care_limit=37)
    assert len(queue) == 48
    assert len([item for item in queue if item.lane == Lane.CARE]) == 37
    assert len([item for item in queue if item.lane == Lane.GROWTH]) == 11
    first_growth = next(index for index, item in enumerate(queue) if item.lane == Lane.GROWTH)
    assert all(item.lane == Lane.CARE for item in queue[:first_growth])


def test_aum_does_not_influence_score(gate):
    """Two clients with the same signal rank the same regardless of size."""
    small = make_client(client_id="C1", aum=2_000_000.0, cash_balance=100_000.0,
                        liquidity_reserve_target=1_000_000.0)
    large = make_client(client_id="C2", aum=400_000_000.0, cash_balance=100_000.0,
                        liquidity_reserve_target=1_000_000.0)
    a = evaluate_client(make_view(client=small), AS_OF, gate)
    b = evaluate_client(make_view(client=large), AS_OF, gate)

    assert a.lane == b.lane == Lane.CARE
    assert a.score == b.score


# ---- suitability ----------------------------------------------------------


def test_off_profile_holding_raises_a_mandatory_care_signal(gate):
    client = make_client(
        risk_profile=RiskProfile.CONSERVATIVE,
        holdings=[
            Holding(
                symbol="DELTA",
                security_type="CS",
                units=100,
                cost_basis=1_000_000,
                market_value=4_000_000,
                asset_class="thai_equity",
                risk_level=RiskProfile.AGGRESSIVE,
            )
        ],
        aum=4_000_000.0,
    )
    item = evaluate_client(make_view(client=client), AS_OF, gate)

    conflict = next(s for s in item.signals if s.code == "SUITABILITY_CONFLICT")
    assert conflict.mandatory
    assert item.lane == Lane.CARE


# ---- permission gate ------------------------------------------------------


def test_growth_is_dropped_entirely_when_contact_is_not_allowed(gate):
    client = make_client(cash_balance=50_000_000.0, liquidity_reserve_target=1_000_000.0)
    permission = Permission(client_id=client.client_id, can_contact=False)
    item = evaluate_client(make_view(client=client, permission=permission), AS_OF, gate)

    assert item is None


def test_care_still_surfaces_when_contact_is_blocked_but_ranks_below(gate):
    client = make_client(cash_balance=100_000.0, liquidity_reserve_target=5_000_000.0)
    blocked = evaluate_client(
        make_view(client=client, permission=Permission(client_id="C9001", can_contact=False)),
        AS_OF, gate,
    )
    allowed = evaluate_client(make_view(client=client), AS_OF, gate)

    assert blocked.lane == Lane.CARE
    assert blocked.contact_allowed is False
    assert blocked.contact_block_reason
    assert blocked.score < allowed.score


# ---- growth evidence bar --------------------------------------------------


def test_unconfirmed_goal_does_not_create_a_growth_signal(gate):
    """The brief asks for confirmed or strongly evidenced need only."""
    client = make_client(cash_balance=1_000_000.0, liquidity_reserve_target=1_000_000.0)
    goal = Goal(
        goal_id="G1",
        client_id=client.client_id,
        goal_type=GoalType.RETIREMENT,
        label="Retirement",
        target_amount=10_000_000,
        target_date=AS_OF + timedelta(days=3650),
        funded_amount=1_000_000,
        priority=3,
        confirmed_with_client=False,
    )
    assert evaluate_client(make_view(client=client, goals=[goal]), AS_OF, gate) is None


def test_confirmed_goal_creates_a_growth_signal(gate):
    client = make_client(cash_balance=1_000_000.0, liquidity_reserve_target=1_000_000.0)
    goal = Goal(
        goal_id="G1",
        client_id=client.client_id,
        goal_type=GoalType.RETIREMENT,
        label="Retirement",
        target_amount=10_000_000,
        target_date=AS_OF + timedelta(days=3650),
        funded_amount=1_000_000,
        priority=3,
        confirmed_with_client=True,
    )
    item = evaluate_client(make_view(client=client, goals=[goal]), AS_OF, gate)
    assert item.lane == Lane.GROWTH
    assert any(s.code == "RETIREMENT_PLANNING_NEED" for s in item.signals)


def test_excess_liquidity_respects_the_reserve(gate):
    """Cash below the reserve is never an opportunity."""
    client = make_client(cash_balance=900_000.0, liquidity_reserve_target=1_000_000.0)
    item = evaluate_client(make_view(client=client), AS_OF, gate)
    assert item.lane == Lane.CARE
    assert not any(s.code == "EXCESS_LIQUIDITY" for s in item.signals + item.suppressed_growth)
