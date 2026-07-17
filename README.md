# RM AI Workstation

An RM workstation that answers four questions: **who needs you today**, **what should you offer them**, **who has gone quiet**, and **whose KYC is about to lapse**.

Built for the five RM problems in [CLAUDE.md](CLAUDE.md): capacity overload, no intelligent prioritisation, product breadth, inactive relationships, and manual KYC tracking.

## The rule that shapes everything

> Business value cannot override mandatory care, suitability, or client-benefit gates.

This is implemented literally, in one place per module, and covered by tests:

- **Module 1** — if a client has any mandatory care signal open, they are assigned the **Care lane** and their growth signals are *suppressed*. The opportunities stay visible on the card so the RM knows what is waiting, but they contribute **nothing** to the score and cannot pull the client into the Growth lane. AUM never enters the score at all: a 400M client and a 2M client with the same signal rank identically.
- **Module 2** — gates (KYC, suitability, mandate, permission, affordability, relevance) run *before* ranking. A gated product is never recommended regardless of fit, and every exclusion is shown with its reason.

## Quick start

Two terminals:

```bash
# 1. API  (http://127.0.0.1:8000)
npm run api

# 2. Frontend  (http://localhost:5173)
npm run install:all   # first time only
npm run dev
```

Your `.env` is set to **live** SETSMART market data. Set `SETSMART_LISTED_DATA_MODE=fixture` to run entirely offline with no key — everything else is mock data either way, so the app works fully without credentials.

```bash
npm run test:py       # 32 tests: gating rules + SETSMART boundary
npm run fixtures      # regenerate the mock data
```

### Prerequisites

- **Python 3.11+** with a working `venv`. This repo's `.venv` was built with pyenv's 3.11.9; the Homebrew 3.12/3.13 on this machine have a broken `pyexpat` and cannot create a usable venv.
- **Node 18+**.

To recreate the venv:

```bash
python3.11 -m venv .venv
.venv/bin/pip install fastapi "uvicorn[standard]" pydantic pydantic-settings httpx python-dotenv pytest
```

## The four pages

| Page | Module | What it answers |
|---|---|---|
| `/attention` | 1 · Attention & Channel | Who to call today, in which lane, and the next best action |
| `/recommend` | 2 · Product Recommendation | Which products fit a client's goals — and which are gated, and why |
| `/activity` | 3 · Active Clients | Who has gone quiet and what money is idle while they do |
| `/kyc` | 4 · KYC & Compliance | Whose KYC blocks advice today, and what to chase |

## Architecture

```
Data sources ──► Data gate ──► Modules ──► FastAPI ──► React frontend
```

The **data gate** ([src/data_gate/gate.py](src/data_gate/gate.py)) is the single access point. Modules never read a source directly. It:

- joins Client 360, Goal Ledger, KYC/CRM and permissions into one `ClientView` per client,
- **recomputes KYC status from the record's dates** rather than trusting the stored label, so a stale nightly batch cannot make an expired KYC look valid,
- answers "may we contact this client at all" before any module ranks anything,
- keeps market data behind one provider with a visible source/degrade flag.

```
src/
  data_gate/      models, config, gate, sources, fixtures
  modules/        attention, recommendation, activity, kyc
  api/            FastAPI service
  frontend/       React + Vite
tools/            generate_fixtures.py
tests/            gating rules + SETSMART boundary (all offline)
```

## Data sources

| Source | Mode | Notes |
|---|---|---|
| Client 360 | Fixture | 48 seeded clients, holdings, cash, activity recency |
| Goal Ledger | Fixture | ~99 goals with funding progress and confirmation flags |
| KYC / CRM | Fixture | Review dates, AML rating, outstanding documents |
| Permission / mandate | Fixture | Contact consent, product entitlements |
| SETSMART listed EOD | **Live** | Real adapter against the published contract — ~3,900 rows/day |

Mock data is generated with a fixed seed and **exact quotas** rather than probabilistic rolls, so the demo composition is a stated fact, not a lottery. (Rolls bit us: a 15%-probability branch landed on 35% of the book at one seed.) Tune the shape in `make_clients()` in [tools/generate_fixtures.py](tools/generate_fixtures.py):

```python
cash_plan = quota(rng, CLIENT_COUNT, {"buffer": 0.50, "excess": 0.35, "short": 0.15})
kyc_plan  = quota(rng, CLIENT_COUNT, {"valid": 0.70, "due_soon": 0.18, "overdue": 0.12})
```

## SETSMART

The adapter in [src/data_gate/sources/setsmart.py](src/data_gate/sources/setsmart.py) implements the **published Listed-company EOD contract only**:

```
GET {base}/eod-price-by-security-type?securityType=&date=&adjustedPriceFlag=
GET {base}/eod-price-by-symbol?symbol=&startDate=&endDate=&adjustedPriceFlag=
auth header: api-key
```

Spec: [Company Fundamental Data API Specification V1.0](https://media.set.or.th/set/Documents/2022/Oct/05_1_Company_Fundamental_Specification.pdf)

**It runs live.** Set in `.env`:

```bash
SETSMART_LISTED_DATA_MODE=live
SETSMART_API_KEY=your_key
```

Set `SETSMART_LISTED_DATA_MODE=fixture` to demo offline with no key.

`GET /api/health` reports the effective mode, and the topbar shows the source and the latest published close — e.g. `SETSMART · Live · close 16 Jul 2026`.

### What live actually gives you

`securityType=All` returns ~3,900 rows: 931 CS, 1,199 DWC, 492 DR, 13 ETF, and **2 UT**. Eleven of the symbols in the mock portfolios are real listed securities and get live closes (PTT, AOT, KBANK, SCB, ADVANC, BDMS, CPALL, DELTA, GULF, TIDLOR, TDEX). The rest are open-end funds and are priced from fixture — they are **not** in this contract, which is exactly the limit the sibling project's `SETSMART_SETUP.md` documents. Nothing is guessed to fill the gap.

**EOD is published after the close, so the current day returns `[]` until then.** The provider walks back day by day to the most recent published close, within `SETSMART_STALE_AFTER_DAYS`. A one-day lag on a weekday morning — or three after a weekend — is normal and is reported as a close date, **not** as a degrade. `degraded_reason` is set only when a live call actually failed and the provider fell back to fixture; conflating the two teaches the RM to ignore the banner.

Boundaries the adapter holds:

- The key is read server-side only. It never appears in a response, an error message, or a log line — there is a test for this. The browser never calls SETSMART.
- `close` is a traded price, not NAV. `bvps` is surfaced as `nav` for listed UT/ETF per the contract — it is **not** a total-return figure.
- Open-end mutual funds have no public contract here and are deliberately **not** modelled. Nothing is guessed.
- A live failure degrades to fixture with a visible reason rather than throwing the request away.
- Rows with a `null` close (securities that did not trade that day) are kept, not dropped — discarding them would silently shrink the universe.

## API

| Endpoint | Purpose |
|---|---|
| `GET /api/health` | Config and provider status (never the key) |
| `GET /api/attention?lane=&limit=` | Module 1 — ranked attention list |
| `GET /api/recommendations?client_id=&goals=&horizon_years=` | Module 2 — ranked products plus exclusions |
| `GET /api/activity?status=` | Module 3 — activity dashboard |
| `GET /api/kyc?status=` | Module 4 — KYC dashboard |
| `GET /api/clients`, `/api/clients/{id}` | Client list and detail |
| `GET /api/products` | Product catalogue |
| `GET /api/market/eod?security_type=` | SETSMART EOD rows with source metadata |

## Design decisions worth knowing

- **Activity ignores RM contact.** Status is measured from the last *client-initiated* event — deposit, withdrawal, or trade. An RM's outbound call does not make a client active, so someone you have chased without response still shows as quiet.
- **Growth needs evidence.** An unconfirmed goal is a hypothesis and raises no growth signal; the brief asks for confirmed or strongly evidenced need.
- **Excess liquidity respects the reserve.** Only cash *above* the client's agreed liquidity reserve is ever treated as investable — in signals and in the affordability gate.
- **Relevance is a gate, not a penalty.** A product addressing none of the selected goals is excluded outright, not ranked low. It was otherwise possible for a money-market fund to be the "best match" for a tax goal on risk-fit points alone.
- **Financing skips the affordability gate.** A loan is a liability, not something funded from spare cash.
- **No model in the loop.** Every gate and score is deterministic and auditable, which is what a suitability decision has to be.

## Known limits

- Everything except SETSMART listed EOD is mock data. Client portfolios are mock holdings that happen to reference real symbols, so live closes are genuine but the positions are not.
- Open-end fund holdings (KFCASH, SCBMONEY, BCAP, TMBBOND…) have no live price — that contract is not public. They show a fixture value.
- The product catalogue is 19 hand-written products, not a real approved shelf. There is no shelf-effective-date or per-client eligibility feed.
- Scoring weights are a first draft, tuned to make the demo legible. They are not calibrated against outcomes.
- Single RM (`RM001`). No auth, no multi-tenant, no audit log.
- Products can tie on score when they are genuinely equivalent on the modelled dimensions.
