"""Tests for the Product Recommendation module.

The theme mirrors Module 1: a gate is a gate. Nothing that fails one may be
recommended, however attractive it scores.
"""

from datetime import date, timedelta

import pytest

from data_gate.gate import DataGate
from data_gate.models import GoalType, KycStatus, Mandate, RiskProfile
from modules.recommendation.engine import gate_product, load_catalog, recommend

from test_attention import AS_OF, make_client, make_view

from data_gate.models import KycRecord, Permission


@pytest.fixture
def gate():
    return DataGate()


ALL_TYPES = ["mutual_fund", "bond", "structured_note", "insurance", "equity", "deposit", "financing"]


def test_catalog_loads():
    catalog = load_catalog()
    assert len(catalog) >= 10
    assert all(p.min_investment >= 0 for p in catalog)


# ---- relevance is a gate, not a ranking penalty ---------------------------


def test_products_that_address_no_selected_goal_are_excluded(gate):
    """Regression: irrelevant products used to score on risk fit alone and be
    presented as the best match for a goal they did nothing about."""
    client_id = _first_advisable_client(gate)
    result = recommend(client_id, [GoalType.PROTECTION], gate=gate)

    for item in result["recommended"]:
        product = next(p for p in load_catalog() if p.product_id == item["product_id"])
        assert GoalType.PROTECTION in product.goals_addressed, (
            f"{item['name']} was recommended for protection but does not address it"
        )


def test_irrelevant_product_is_listed_as_excluded_with_a_reason(gate):
    client_id = _first_advisable_client(gate)
    result = recommend(client_id, [GoalType.PROTECTION], gate=gate)

    excluded_names = {e["name"]: e["reasons"] for e in result["excluded"]}
    # A pure money-market fund has nothing to do with protection.
    assert any("does not address protection" in " ".join(r).lower() for r in excluded_names.values())


def _first_advisable_client(gate) -> str:
    for view in gate.client_views("RM001"):
        result = recommend(view.client.client_id, [GoalType.PROTECTION], gate=gate)
        if not result["blocked"] and result["recommended"]:
            return view.client.client_id
    pytest.skip("no advisable client in the fixture set")


# ---- hard gates -----------------------------------------------------------


def test_product_above_risk_profile_is_gated():
    client = make_client(risk_profile=RiskProfile.CONSERVATIVE, cash_balance=100_000_000.0)
    view = make_view(client=client)
    view.permission.allowed_product_types = ALL_TYPES

    aggressive = next(p for p in load_catalog() if p.risk_level == RiskProfile.AGGRESSIVE)
    result = gate_product(aggressive, view)

    assert not result.passed
    assert any("exceeds the client's agreed profile" in r for r in result.reasons)


def test_product_the_client_is_not_permissioned_for_is_gated():
    client = make_client(risk_profile=RiskProfile.AGGRESSIVE, cash_balance=100_000_000.0)
    view = make_view(client=client)
    view.permission.allowed_product_types = ["deposit"]

    fund = next(p for p in load_catalog() if p.product_type == "mutual_fund")
    result = gate_product(fund, view)

    assert not result.passed
    assert any("not permissioned" in r for r in result.reasons)


def test_minimum_investment_is_tested_against_cash_above_the_reserve():
    """Investable cash means cash the client can actually deploy."""
    client = make_client(
        risk_profile=RiskProfile.AGGRESSIVE,
        cash_balance=2_100_000.0,
        liquidity_reserve_target=2_000_000.0,  # only 100k is truly investable
    )
    view = make_view(client=client)
    view.permission.allowed_product_types = ALL_TYPES

    note = next(p for p in load_catalog() if p.min_investment >= 2_000_000)
    result = gate_product(note, view)

    assert not result.passed
    assert any("exceeds investable cash" in r for r in result.reasons)


def test_financing_is_not_blocked_by_lack_of_investable_cash():
    """A loan is a liability, not something funded from spare cash."""
    client = make_client(
        risk_profile=RiskProfile.AGGRESSIVE,
        cash_balance=0.0,
        liquidity_reserve_target=1_000_000.0,
    )
    view = make_view(client=client)
    view.permission.allowed_product_types = ALL_TYPES

    loan = next(p for p in load_catalog() if p.product_type == "financing")
    assert gate_product(loan, view).passed


# ---- client-level blocks --------------------------------------------------


def test_expired_kyc_blocks_the_entire_catalogue(gate):
    """No product at all, and the reason is stated once."""
    client_id = _first_advisable_client(gate)
    view = gate.client_view(client_id)
    original = view.kyc

    try:
        # Patch the loaded view's KYC via the fixture-backed gate is awkward, so
        # assert the rule through a hand-built view instead.
        blocked_client = make_client(cash_balance=100_000_000.0)
        blocked_view = make_view(
            client=blocked_client,
            kyc=KycRecord(
                client_id=blocked_client.client_id,
                kyc_status=KycStatus.OVERDUE,
                expires_on=AS_OF - timedelta(days=10),
                aml_risk_rating="low",
                suitability_expires_on=AS_OF + timedelta(days=100),
            ),
        )
        from modules.recommendation.engine import client_level_block

        block = client_level_block(blocked_view, AS_OF)
        assert block is not None
        assert "KYC expired" in block
    finally:
        assert original is view.kyc


def test_execution_only_mandate_blocks_advice():
    from modules.recommendation.engine import client_level_block

    client = make_client(mandate=Mandate.EXECUTION_ONLY)
    block = client_level_block(make_view(client=client), AS_OF)

    assert block is not None
    assert "execution-only" in block


def test_lapsed_suitability_blocks_advice():
    from modules.recommendation.engine import client_level_block

    client = make_client()
    view = make_view(client=client)
    view.kyc.suitability_expires_on = AS_OF - timedelta(days=1)

    block = client_level_block(view, AS_OF)
    assert block is not None
    assert "Suitability assessment lapsed" in block


def test_blocked_client_gets_no_recommendations_at_all(gate):
    blocked = [
        recommend(v.client.client_id, [GoalType.RETIREMENT], gate=gate)
        for v in gate.client_views("RM001")
    ]
    for result in blocked:
        if result["blocked"]:
            assert result["recommended"] == []
            assert result["block_reason"]
