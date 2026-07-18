"""SETSMART Listed-company EOD provider.

Implements the published contract only:
  GET {base}/eod-price-by-security-type?securityType=&date=&adjustedPriceFlag=
  GET {base}/eod-price-by-symbol?symbol=&startDate=&endDate=&adjustedPriceFlag=
  auth header: api-key

Spec: Company Fundamental Data API Specification V1.0
https://media.set.or.th/set/Documents/2022/Oct/05_1_Company_Fundamental_Specification.pdf

Boundaries this module holds:
  - The API key is read server-side and never appears in a return value, an
    exception message, or a log line.
  - `close` is the traded price of a listed security, not NAV.
  - `bvps` is surfaced as `nav` for listed UT/ETF per the contract. It is not a
    total-return figure, and it says nothing about open-end funds, which have no
    public contract here and are therefore not modelled.
  - Live failure degrades to fixture with a visible reason rather than throwing
    the whole request away.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import date, timedelta
from threading import Lock
from typing import Any, Optional

import httpx

from ..config import FIXTURE_DIR, Settings, get_settings
from ..models import EodPrice

logger = logging.getLogger(__name__)

# Security types defined by the contract.
SECURITY_TYPES = {"All", "CS", "CSF", "PS", "PSF", "W", "TSR", "DWC", "DWP", "DR", "ETF", "UT"}

# bvps carries NAV semantics only for these listed types.
NAV_BEARING_TYPES = {"UT", "ETF"}


@dataclass
class EodResult:
    rows: list[EodPrice]
    source: str  # "live" | "fixture"
    as_of: Optional[date]
    # Set only when something is actually wrong — a live call failed and we fell
    # back to fixture. Normal market lag is NOT a degrade; conflating the two
    # teaches the RM to ignore the banner.
    degraded_reason: Optional[str] = None
    # Trading days between the business date and the latest published close.
    # 1 on any normal morning, 3 after a weekend. Informational.
    lag_days: int = 0

    def meta(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "as_of": self.as_of.isoformat() if self.as_of else None,
            "row_count": len(self.rows),
            "degraded_reason": self.degraded_reason,
            "lag_days": self.lag_days,
        }


class SetsmartError(Exception):
    """Raised for contract/validation problems. Never carries credentials."""


def _optional_number(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_row(row: dict[str, Any]) -> EodPrice:
    security_type = str(row.get("securityType") or "").upper()
    bvps = _optional_number(row.get("bvps"))
    nav = bvps if security_type in NAV_BEARING_TYPES else None
    return EodPrice(
        date=date.fromisoformat(str(row["date"])[:10]),
        symbol=str(row["symbol"]).strip(),
        security_type=security_type,
        close=_optional_number(row.get("close")),
        prior=_optional_number(row.get("prior")),
        pe=_optional_number(row.get("pe")),
        pbv=_optional_number(row.get("pbv")),
        bvps=bvps,
        dividend_yield=_optional_number(row.get("dividendYield")),
        market_cap=_optional_number(row.get("marketCap")),
        nav=nav,
    )


class SetsmartListedProvider:
    """Fetches listed EOD rows, live or from fixture, behind one interface."""

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()
        self._cache: dict[str, tuple[float, EodResult]] = {}
        # FastAPI executes synchronous endpoints in a thread pool. Without a
        # single-flight lock, one page load can send several identical live
        # requests before the first response populates the cache, triggering
        # a 429 and mixing Live/Fixture badges within the same screen.
        self._fetch_lock = Lock()

    # ---- fixture path -------------------------------------------------

    def _fixture_rows(self) -> list[EodPrice]:
        path = FIXTURE_DIR / "setsmart_eod.json"
        if not path.exists():
            return []
        payload = json.loads(path.read_text())
        rows = []
        for raw in payload.get("rows", []):
            try:
                rows.append(_normalize_row(raw))
            except (KeyError, ValueError) as exc:
                logger.warning("skipping malformed fixture row: %s", exc)
        return rows

    def _fixture_result(self, degraded_reason: Optional[str] = None) -> EodResult:
        rows = self._fixture_rows()
        as_of = max((r.date for r in rows), default=None)
        for row in rows:
            row.source = "fixture"
        return EodResult(
            rows=rows, source="fixture", as_of=as_of, degraded_reason=degraded_reason
        )

    # ---- live path ----------------------------------------------------

    def _live_get(self, path: str, params: dict[str, Any]) -> Any:
        """One live call with bounded retry. Raises SetsmartError, never leaks the key."""
        url = f"{self.settings.setsmart_base_url}/{path}"
        headers = {"api-key": self.settings.setsmart_api_key}
        timeout = self.settings.setsmart_timeout_ms / 1000
        last_error = "unknown"

        for attempt in range(self.settings.setsmart_max_retries + 1):
            try:
                response = httpx.get(url, params=params, headers=headers, timeout=timeout)
            except httpx.RequestError as exc:
                last_error = f"transport error: {type(exc).__name__}"
            else:
                if response.status_code == 200:
                    try:
                        return response.json()
                    except ValueError:
                        raise SetsmartError("response was not valid JSON") from None
                if response.status_code in (401, 403):
                    # Not retryable. Do not echo the response body — it may quote the key.
                    raise SetsmartError(
                        f"authentication rejected by SETSMART (HTTP {response.status_code}); "
                        "the API key is missing, expired, or revoked"
                    )
                if response.status_code == 429:
                    last_error = "rate limited (HTTP 429)"
                elif 400 <= response.status_code < 500:
                    raise SetsmartError(f"request rejected (HTTP {response.status_code})")
                else:
                    last_error = f"upstream error (HTTP {response.status_code})"

            if attempt < self.settings.setsmart_max_retries:
                time.sleep(self.settings.setsmart_retry_base_ms * (2**attempt) / 1000)

        raise SetsmartError(f"live fetch failed after retries: {last_error}")

    # ---- public interface ---------------------------------------------

    def _fetch_one_day(self, security_type: str, on: date, adjusted: str) -> list[EodPrice]:
        """Rows for exactly one date. An empty list means the market was closed
        or the day is not published yet — both are normal, not errors."""
        payload = self._live_get(
            "eod-price-by-security-type",
            {
                "securityType": security_type,
                "date": on.isoformat(),
                "adjustedPriceFlag": adjusted,
            },
        )
        raw_rows = payload if isinstance(payload, list) else payload.get("data", [])
        rows = []
        for raw in raw_rows:
            try:
                row = _normalize_row(raw)
            except (KeyError, ValueError) as exc:
                logger.warning("skipping malformed live row: %s", exc)
                continue
            row.source = "live"
            rows.append(row)
        return rows

    def eod_by_security_type(
        self, security_type: str = "All", on: Optional[date] = None, adjusted: str = "Y"
    ) -> EodResult:
        if security_type not in SECURITY_TYPES:
            raise SetsmartError(f"unknown securityType: {security_type}")

        if not self.settings.live_enabled:
            reason = None
            if self.settings.setsmart_listed_data_mode == "live":
                reason = "live mode requested but SETSMART_API_KEY is not set"
            return self._fixture_result(reason)

        on = on or self.settings.as_of
        cache_key = f"{security_type}:{on.isoformat()}:{adjusted}"
        cached = self._cache.get(cache_key)
        if cached and (time.monotonic() - cached[0]) * 1000 < self.settings.setsmart_cache_ttl_ms:
            return cached[1]
        with self._fetch_lock:
            # Recheck after waiting: another request may have completed the
            # identical fetch while this request was blocked on the lock.
            cached = self._cache.get(cache_key)
            if cached and (time.monotonic() - cached[0]) * 1000 < self.settings.setsmart_cache_ttl_ms:
                return cached[1]

            # EOD for the current day is not published until after the close,
            # and weekends/holidays have no data. Walk back only within the
            # configured stale window.
            try:
                rows: list[EodPrice] = []
                resolved = on
                for back in range(self.settings.setsmart_stale_after_days + 1):
                    resolved = on - timedelta(days=back)
                    rows = self._fetch_one_day(security_type, resolved, adjusted)
                    if rows:
                        break
            except SetsmartError as exc:
                logger.warning("SETSMART live unavailable, using fixture: %s", exc)
                result = self._fixture_result(str(exc))
                self._cache[cache_key] = (time.monotonic(), result)
                return result

            if not rows:
                result = self._fixture_result(
                    f"no published EOD data in the {self.settings.setsmart_stale_after_days} "
                    f"days to {on.isoformat()}"
                )
                self._cache[cache_key] = (time.monotonic(), result)
                return result

            result = EodResult(
                rows=rows,
                source="live",
                as_of=resolved,
                lag_days=(on - resolved).days,
            )
            self._cache[cache_key] = (time.monotonic(), result)
            return result

    def health(self) -> dict[str, Any]:
        """Provider status with no credential material in it."""
        status = self.settings.public_status()
        if not self.settings.live_enabled:
            status["reachable"] = None
            status["detail"] = "fixture mode; no live call attempted"
            return status
        try:
            # An empty day is a valid response, so this asks whether the contract
            # answers at all — not whether today happens to have data.
            self._live_get(
                "eod-price-by-security-type",
                {
                    "securityType": "UT",
                    "date": self.settings.as_of.isoformat(),
                    "adjustedPriceFlag": "Y",
                },
            )
            status["reachable"] = True
            status["detail"] = "live contract responded"
        except SetsmartError as exc:
            status["reachable"] = False
            status["detail"] = str(exc)
        return status
