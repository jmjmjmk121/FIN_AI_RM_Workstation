"""Tests for the SETSMART provider boundary.

These run offline. The live contract is exercised by stubbing the one method
that performs HTTP, so the suite never depends on a key or the network.
"""

from datetime import date
from concurrent.futures import ThreadPoolExecutor
import time

import pytest

from data_gate.config import Settings
from data_gate.sources.setsmart import SetsmartError, SetsmartListedProvider

AS_OF = date(2026, 7, 17)


def live_settings(**overrides) -> Settings:
    base = dict(
        setsmart_listed_data_mode="live",
        setsmart_api_key="test-key-not-real",
        rm_as_of_date=AS_OF.isoformat(),
    )
    base.update(overrides)
    return Settings(**base)


def row(on: date, symbol: str = "PTT", security_type: str = "CS", **extra) -> dict:
    payload = {
        "date": on.isoformat(),
        "symbol": symbol,
        "securityType": security_type,
        "adjustedPriceFlag": "Y",
        "close": 38.75,
        "prior": 38.5,
        "bvps": 12.5,
    }
    payload.update(extra)
    return payload


# ---- the empty-today problem ---------------------------------------------


def test_walks_back_to_the_last_published_close(monkeypatch):
    """Today's EOD is not published until after the close, and weekends have
    none at all. An empty today must not hand the modules an empty market."""
    provider = SetsmartListedProvider(live_settings())
    published = date(2026, 7, 14)
    calls = []

    def fake_get(path, params):
        asked = date.fromisoformat(params["date"])
        calls.append(asked)
        return [row(published)] if asked == published else []

    monkeypatch.setattr(provider, "_live_get", fake_get)
    result = provider.eod_by_security_type("CS")

    assert result.source == "live"
    assert result.as_of == published
    assert result.lag_days == 3
    # It asked for each day in turn and stopped as soon as it found data.
    assert calls == [date(2026, 7, 17), date(2026, 7, 16), date(2026, 7, 15), published]


def test_a_normal_one_day_lag_is_not_reported_as_degraded(monkeypatch):
    """Crying 'degraded' every morning teaches the RM to ignore the banner."""
    provider = SetsmartListedProvider(live_settings())
    yesterday = date(2026, 7, 16)

    monkeypatch.setattr(
        provider,
        "_live_get",
        lambda path, params: [row(yesterday)] if params["date"] == yesterday.isoformat() else [],
    )
    result = provider.eod_by_security_type("CS")

    assert result.lag_days == 1
    assert result.degraded_reason is None


def test_no_data_within_the_stale_window_falls_back_to_fixture(monkeypatch):
    provider = SetsmartListedProvider(live_settings(setsmart_stale_after_days=3))
    monkeypatch.setattr(provider, "_live_get", lambda path, params: [])

    result = provider.eod_by_security_type("CS")

    assert result.source == "fixture"
    assert "no published EOD data" in result.degraded_reason


# ---- failure handling -----------------------------------------------------


def test_auth_failure_degrades_to_fixture_with_a_stated_reason(monkeypatch):
    provider = SetsmartListedProvider(live_settings())

    def boom(path, params):
        raise SetsmartError("authentication rejected by SETSMART (HTTP 401)")

    monkeypatch.setattr(provider, "_live_get", boom)
    result = provider.eod_by_security_type("CS")

    assert result.source == "fixture"
    assert "401" in result.degraded_reason
    assert result.rows, "fixture rows should still be served"


def test_failed_live_call_is_cached_during_fallback_ttl(monkeypatch):
    provider = SetsmartListedProvider(live_settings())
    calls = 0

    def boom(path, params):
        nonlocal calls
        calls += 1
        raise SetsmartError("authentication rejected by SETSMART (HTTP 401)")

    monkeypatch.setattr(provider, "_live_get", boom)
    first = provider.eod_by_security_type("CS")
    second = provider.eod_by_security_type("CS")

    assert first.source == second.source == "fixture"
    assert calls == 1


def test_concurrent_first_load_uses_one_live_request(monkeypatch):
    provider = SetsmartListedProvider(live_settings())
    calls = 0

    def slow_success(path, params):
        nonlocal calls
        calls += 1
        time.sleep(0.03)
        return [row(AS_OF)]

    monkeypatch.setattr(provider, "_live_get", slow_success)
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _: provider.eod_by_security_type("All"), range(8)))

    assert calls == 1
    assert all(result is results[0] for result in results)
    assert all(result.source == "live" for result in results)


def test_live_mode_without_a_key_falls_back_to_fixture():
    provider = SetsmartListedProvider(live_settings(setsmart_api_key=""))
    result = provider.eod_by_security_type("CS")

    assert result.source == "fixture"
    assert "not set" in result.degraded_reason


def test_unknown_security_type_is_rejected():
    provider = SetsmartListedProvider(live_settings())
    with pytest.raises(SetsmartError):
        provider.eod_by_security_type("NOT_A_TYPE")


# ---- contract semantics ---------------------------------------------------


def test_bvps_is_nav_only_for_listed_ut_and_etf(monkeypatch):
    """Per the contract, bvps carries NAV semantics for UT/ETF only — and even
    then it is not a total-return figure."""
    provider = SetsmartListedProvider(live_settings())
    on = AS_OF

    monkeypatch.setattr(
        provider,
        "_live_get",
        lambda path, params: [
            row(on, "PTT", "CS", bvps=12.5),
            row(on, "TDEX", "ETF", bvps=10.4),
            row(on, "SCBSET", "UT", bvps=18.68),
        ],
    )
    rows = {r.symbol: r for r in provider.eod_by_security_type("All").rows}

    assert rows["PTT"].nav is None
    assert rows["TDEX"].nav == 10.4
    assert rows["SCBSET"].nav == 18.68


def test_untraded_rows_with_null_close_are_kept(monkeypatch):
    """SETSMART returns real rows with a null close for securities that did not
    trade. Dropping them would silently shrink the universe."""
    provider = SetsmartListedProvider(live_settings())

    monkeypatch.setattr(
        provider,
        "_live_get",
        lambda path, params: [row(AS_OF, "SCBSET", "UT", close=None, prior=7.54)],
    )
    rows = provider.eod_by_security_type("UT").rows

    assert len(rows) == 1
    assert rows[0].close is None
    assert rows[0].change_pct is None


def test_the_api_key_never_appears_in_an_error(monkeypatch):
    provider = SetsmartListedProvider(live_settings(setsmart_api_key="super-secret-key"))

    class FakeResponse:
        status_code = 401
        text = "denied for key super-secret-key"

        def json(self):
            return {"message": "denied for key super-secret-key"}

    monkeypatch.setattr("httpx.get", lambda *a, **k: FakeResponse())

    with pytest.raises(SetsmartError) as exc:
        provider._live_get("eod-price-by-security-type", {"date": "2026-07-16"})

    assert "super-secret-key" not in str(exc.value)
