"""Generate deterministic mock fixtures for Client 360, Goal Ledger, KYC/CRM,
permissions, and a SETSMART listed-EOD fallback set.

Seeded, so the demo is identical on every machine and every run:
    .venv/bin/python tools/generate_fixtures.py
"""

from __future__ import annotations

import json
import random
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

FIXTURE_DIR = ROOT / "src" / "data_gate" / "fixtures"
AS_OF = date(2026, 7, 17)
SEED = 20260717
RM_ID = "RM001"
CLIENT_COUNT = 48

FIRST_NAMES = [
    "Somchai", "Suchada", "Anong", "Wichai", "Pornthip", "Kittisak", "Malee",
    "Chaiwat", "Siriporn", "Narong", "Rattana", "Prasert", "Wanida", "Thanakorn",
    "Kanya", "Surasak", "Napaporn", "Boonmee", "Ratchanee", "Adisorn", "Pimchanok",
    "Weerachai", "Sunisa", "Chalermchai",
]
LAST_NAMES = [
    "Charoensuk", "Rattanaporn", "Srisawat", "Wongsiri", "Thongchai", "Piyawat",
    "Sae-Lim", "Chaiyaphum", "Ratanakul", "Boonyarat", "Vongsakul", "Intharaphan",
]
SEGMENTS = ["Priority", "Wealth", "Private", "Affluent"]
RISK_PROFILES = ["conservative", "moderate", "balanced", "growth", "aggressive"]
MANDATES = ["execution_only", "advisory", "advisory", "advisory", "discretionary"]

# symbol, security_type, asset_class, risk_level
UNIVERSE = [
    ("PTT", "CS", "thai_equity", "growth"),
    ("AOT", "CS", "thai_equity", "growth"),
    ("CPALL", "CS", "thai_equity", "growth"),
    ("SCB", "CS", "thai_equity", "balanced"),
    ("KBANK", "CS", "thai_equity", "balanced"),
    ("ADVANC", "CS", "thai_equity", "balanced"),
    ("BDMS", "CS", "thai_equity", "balanced"),
    ("DELTA", "CS", "thai_equity", "aggressive"),
    ("GULF", "CS", "thai_equity", "growth"),
    ("TIDLOR", "CS", "thai_equity", "aggressive"),
    ("TDEX", "ETF", "equity_etf", "balanced"),
    ("ESETTF", "ETF", "equity_etf", "balanced"),
    ("BCAP", "UT", "unit_trust", "moderate"),
    ("KFLTFDIV", "UT", "unit_trust", "moderate"),
    ("TGOLDETF", "ETF", "commodity_etf", "growth"),
    # Low-risk names, so a conservative client can hold an on-profile portfolio.
    ("KFCASH", "UT", "money_market", "conservative"),
    ("SCBMONEY", "UT", "money_market", "conservative"),
    ("KTGOVBOND", "UT", "bond_fund", "conservative"),
    ("TMBBOND", "UT", "bond_fund", "moderate"),
]
BOND_UNIVERSE = [
    ("GOVBOND5Y", "bond", "conservative"),
    ("CORPBOND3Y", "bond", "moderate"),
    ("TBILL6M", "money_market", "conservative"),
]

GOAL_TEMPLATES = [
    ("retirement", "Retirement income at 60", 1, 12_000_000),
    ("education", "Children's overseas education", 2, 4_500_000),
    ("protection", "Family income protection", 1, 3_000_000),
    ("liquidity", "Emergency reserve", 2, 1_200_000),
    ("wealth_transfer", "Estate transfer to next generation", 3, 20_000_000),
    ("financing", "Property purchase financing", 3, 8_000_000),
    ("tax", "Annual tax-efficient allocation", 4, 500_000),
]

ISSUE_SUMMARIES = [
    "Statement discrepancy raised, unresolved",
    "Fee rebate promised, not yet applied",
    "Failed transfer instruction, awaiting operations",
    "Complaint on advice suitability, under review",
]


def money(rng, low, high, step=10_000):
    return float(round(rng.uniform(low, high) / step) * step)


def quota(rng, n, weights):
    """Assign one label per client with exact proportions, then shuffle.

    Probabilistic rolls give a demo whose shape drifts with the seed — at one
    point a 15% branch landed on 35% of the book. Quotas make the composition a
    stated fact rather than a lottery, which is what a demo needs.
    """
    labels = []
    for label, share in weights.items():
        labels.extend([label] * round(n * share))
    # Fix any rounding drift against the largest bucket.
    dominant = max(weights, key=weights.get)
    while len(labels) < n:
        labels.append(dominant)
    del labels[n:]
    rng.shuffle(labels)
    return labels


def make_clients(rng):
    clients, goals, kyc_records, permissions = [], [], [], []
    used_names = set()

    # The demo's shape, stated up front rather than left to the RNG.
    cash_plan = quota(rng, CLIENT_COUNT, {"buffer": 0.50, "excess": 0.35, "short": 0.15})
    activity_plan = quota(rng, CLIENT_COUNT, {"active": 0.45, "cooling": 0.25, "idle": 0.30})
    kyc_plan = quota(rng, CLIENT_COUNT, {"valid": 0.70, "due_soon": 0.18, "overdue": 0.12})
    issue_plan = quota(rng, CLIENT_COUNT, {"none": 0.90, "open": 0.10})
    docs_plan = quota(rng, CLIENT_COUNT, {"complete": 0.92, "missing": 0.08})
    offprofile_plan = quota(rng, CLIENT_COUNT, {"on": 0.88, "off": 0.12})

    for i in range(CLIENT_COUNT):
        client_id = f"C{1001 + i}"

        while True:
            name = f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"
            if name not in used_names:
                used_names.add(name)
                break

        segment = rng.choice(SEGMENTS)
        risk_profile = rng.choice(RISK_PROFILES)
        mandate = rng.choice(MANDATES)
        age = rng.randint(28, 74)
        dob = date(AS_OF.year - age, rng.randint(1, 12), rng.randint(1, 28))

        base_aum = {
            "Affluent": (2_000_000, 10_000_000),
            "Priority": (8_000_000, 40_000_000),
            "Wealth": (30_000_000, 120_000_000),
            "Private": (100_000_000, 500_000_000),
        }[segment]

        # ---- holdings -------------------------------------------------
        # Portfolios normally respect the client's agreed risk profile. A
        # minority breach it on purpose, so the suitability gate has something
        # real to catch without the whole book looking non-compliant.
        holdings = []
        n_holdings = rng.randint(4, 8)
        target_aum = money(rng, *base_aum, step=100_000)

        ceiling = RISK_PROFILES.index(risk_profile)
        on_profile = [u for u in UNIVERSE if RISK_PROFILES.index(u[3]) <= ceiling]
        off_profile = [u for u in UNIVERSE if RISK_PROFILES.index(u[3]) > ceiling]

        # Conservative clients can run out of on-profile names; fall back to the
        # lowest-risk instruments rather than forcing a breach.
        if len(on_profile) < 2:
            on_profile = sorted(UNIVERSE, key=lambda u: RISK_PROFILES.index(u[3]))[:4]

        picks = rng.sample(on_profile, min(n_holdings, len(on_profile)))
        if off_profile and offprofile_plan[i] == "off":
            picks.append(rng.choice(off_profile))

        weights = [rng.uniform(0.95, 1.15) for _ in picks]

        # Every 7th client gets a deliberate concentration for the care gate.
        if i % 7 == 0 and weights:
            weights[0] = sum(weights) * 1.5

        total_weight = sum(weights)
        for (symbol, sec_type, asset_class, risk_level), weight in zip(picks, weights):
            mv = round(target_aum * weight / total_weight, 2)
            holdings.append(
                {
                    "symbol": symbol,
                    "security_type": sec_type,
                    "units": round(mv / rng.uniform(10, 250), 2),
                    "cost_basis": round(mv * rng.uniform(0.72, 1.18), 2),
                    "market_value": mv,
                    "asset_class": asset_class,
                    "risk_level": risk_level,
                    "maturity_date": None,
                }
            )

        # Some clients hold a maturing instrument — a re-engagement trigger.
        if i % 5 == 0:
            symbol, asset_class, risk_level = rng.choice(BOND_UNIVERSE)
            mv = money(rng, 500_000, 6_000_000)
            maturity = AS_OF + timedelta(days=rng.randint(-120, 75))
            holdings.append(
                {
                    "symbol": symbol,
                    "security_type": "BOND",
                    "units": round(mv / 1000, 2),
                    "cost_basis": mv,
                    "market_value": mv,
                    "asset_class": asset_class,
                    "risk_level": risk_level,
                    "maturity_date": maturity.isoformat(),
                }
            )

        aum = round(sum(h["market_value"] for h in holdings), 2)

        # ---- cash vs reserve ------------------------------------------
        reserve = money(rng, 300_000, 3_000_000, step=50_000)
        if cash_plan[i] == "short":
            cash = round(reserve * rng.uniform(0.1, 0.7), 2)               # -> care gate
        elif cash_plan[i] == "excess":
            cash = round(reserve + money(rng, 2_000_000, 40_000_000), 2)   # -> growth lane
        else:
            cash = round(reserve * rng.uniform(1.0, 1.6), 2)

        # ---- activity recency -----------------------------------------
        span = {
            "idle": (400, 900),
            "cooling": (120, 400),
            "active": (1, 100),
        }[activity_plan[i]]
        last_trade = AS_OF - timedelta(days=rng.randint(*span))
        last_deposit = AS_OF - timedelta(days=rng.randint(span[0], span[1] + 200))
        last_withdrawal = AS_OF - timedelta(days=rng.randint(span[0], span[1] + 300))
        last_contact = AS_OF - timedelta(days=rng.randint(1, 500))

        # ---- service issues -------------------------------------------
        issues = []
        if issue_plan[i] == "open":
            issues.append(
                {
                    "issue_id": f"S{client_id}-1",
                    "opened_on": (AS_OF - timedelta(days=rng.randint(3, 90))).isoformat(),
                    "summary": rng.choice(ISSUE_SUMMARIES),
                    "severity": rng.randint(2, 5),
                    "resolved": False,
                }
            )

        is_vulnerable = age >= 72 or rng.random() < 0.03

        clients.append(
            {
                "client_id": client_id,
                "name": name,
                "rm_id": RM_ID,
                "segment": segment,
                "date_of_birth": dob.isoformat(),
                "risk_profile": risk_profile,
                "suitability_reviewed_on": (
                    AS_OF - timedelta(days=rng.randint(30, 900))
                ).isoformat(),
                "mandate": mandate,
                "aum": aum,
                "cash_balance": cash,
                "liquidity_reserve_target": reserve,
                "holdings": holdings,
                "service_issues": issues,
                "is_vulnerable": is_vulnerable,
                "vulnerability_note": (
                    "Age-related: enhanced care required" if age >= 72
                    else "Flagged by RM: recent bereavement" if is_vulnerable
                    else None
                ),
                "last_contact_on": last_contact.isoformat(),
                "last_deposit_on": last_deposit.isoformat(),
                "last_withdrawal_on": last_withdrawal.isoformat(),
                "last_trade_on": last_trade.isoformat(),
            }
        )

        # ---- goals ----------------------------------------------------
        for j, (goal_type, label, priority, base) in enumerate(
            rng.sample(GOAL_TEMPLATES, rng.randint(1, 3))
        ):
            target = money(rng, base * 0.6, base * 1.6, step=100_000)
            funded_ratio = rng.uniform(0.35, 1.05)
            years_out = rng.randint(1, 22) if goal_type == "retirement" else rng.randint(1, 12)
            goals.append(
                {
                    "goal_id": f"G{client_id}-{j + 1}",
                    "client_id": client_id,
                    "goal_type": goal_type,
                    "label": label,
                    "target_amount": target,
                    "target_date": date(
                        AS_OF.year + years_out, rng.randint(1, 12), rng.randint(1, 28)
                    ).isoformat(),
                    "funded_amount": round(target * funded_ratio, 2),
                    "priority": priority,
                    "confirmed_with_client": rng.random() < 0.72,
                }
            )

        # ---- KYC ------------------------------------------------------
        if kyc_plan[i] == "overdue":
            expires = AS_OF - timedelta(days=rng.randint(5, 200))
        elif kyc_plan[i] == "due_soon":
            expires = AS_OF + timedelta(days=rng.randint(1, 60))
        else:
            expires = AS_OF + timedelta(days=rng.randint(90, 900))

        missing = []
        if docs_plan[i] == "missing":
            missing = rng.sample(
                ["Proof of address", "Source of wealth declaration", "Updated ID copy",
                 "Tax residency self-certification"],
                rng.randint(1, 2),
            )

        kyc_records.append(
            {
                "client_id": client_id,
                "kyc_status": "missing" if missing else "valid",  # gate recomputes from dates
                "last_review_on": (expires - timedelta(days=730)).isoformat(),
                "expires_on": expires.isoformat(),
                "aml_risk_rating": rng.choice(["low", "low", "medium", "medium", "high"]),
                "missing_documents": missing,
                "suitability_expires_on": (
                    AS_OF + timedelta(days=rng.randint(-40, 800))
                ).isoformat(),
            }
        )

        # ---- permissions ----------------------------------------------
        allowed = ["mutual_fund", "bond", "structured_note", "insurance", "equity", "deposit"]
        if mandate == "execution_only":
            allowed = ["equity", "deposit", "bond"]
        if rng.random() < 0.10:
            allowed.remove(rng.choice([a for a in allowed if a != "deposit"]))

        permissions.append(
            {
                "client_id": client_id,
                "can_contact": rng.random() > 0.05,
                "marketing_consent": rng.random() > 0.25,
                "allowed_product_types": allowed,
                "do_not_disturb_until": (
                    (AS_OF + timedelta(days=rng.randint(5, 45))).isoformat()
                    if rng.random() < 0.07
                    else None
                ),
            }
        )

    return clients, goals, kyc_records, permissions


def make_eod(rng, clients):
    """Fallback EOD rows for every symbol clients actually hold."""
    symbols = {
        (h["symbol"], h["security_type"])
        for c in clients
        for h in c["holdings"]
        if h["security_type"] in {"CS", "ETF", "UT"}
    }
    rows = []
    for symbol, sec_type in sorted(symbols):
        close = round(rng.uniform(8, 320), 2)
        prior = round(close * rng.uniform(0.96, 1.04), 2)
        bvps = round(close * rng.uniform(0.55, 1.25), 4)
        rows.append(
            {
                "date": AS_OF.isoformat(),
                "symbol": symbol,
                "securityType": sec_type,
                "adjustedPriceFlag": "Y",
                "prior": prior,
                "open": round(prior * rng.uniform(0.99, 1.01), 2),
                "high": round(close * rng.uniform(1.0, 1.03), 2),
                "low": round(close * rng.uniform(0.97, 1.0), 2),
                "close": close,
                "average": round((close + prior) / 2, 2),
                "totalVolume": rng.randint(100_000, 40_000_000),
                "totalValue": rng.randint(1_000_000, 900_000_000),
                "pe": round(rng.uniform(6, 34), 2),
                "pbv": round(rng.uniform(0.6, 5.5), 2),
                "bvps": bvps,
                "dividendYield": round(rng.uniform(0.4, 6.5), 2),
                "marketCap": rng.randint(2_000_000_000, 900_000_000_000),
            }
        )
    return {
        "contract": "SETSMART Listed-company EOD API Specification V1.0",
        "note": (
            "Offline fallback rows. Shape mirrors the live contract. "
            "bvps is NAV for listed UT/ETF only, and is not a total-return figure."
        ),
        "as_of": AS_OF.isoformat(),
        "rows": rows,
    }


def main() -> None:
    rng = random.Random(SEED)
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)

    clients, goals, kyc_records, permissions = make_clients(rng)
    eod = make_eod(rng, clients)

    payloads = {
        "clients.json": clients,
        "goals.json": goals,
        "kyc.json": kyc_records,
        "permissions.json": permissions,
        "setsmart_eod.json": eod,
    }
    for filename, payload in payloads.items():
        (FIXTURE_DIR / filename).write_text(json.dumps(payload, indent=2, ensure_ascii=False))
        print(f"wrote {filename}")

    print(
        f"\n{len(clients)} clients, {len(goals)} goals, "
        f"{len(kyc_records)} KYC records, {len(eod['rows'])} EOD rows @ {AS_OF}"
    )


if __name__ == "__main__":
    main()
