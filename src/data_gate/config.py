"""Runtime configuration. Secrets are read server-side only and never returned."""

from __future__ import annotations

from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Literal, Optional
from zoneinfo import ZoneInfo

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
# The supplied project lives under `CFA_AI/release/rm-workstation`; the user
# already keeps non-committed workspace credentials at `CFA_AI/.env.local`.
# Load that file only as a fallback. Project-local files have higher priority.
WORKSPACE_ROOT = PROJECT_ROOT.parents[1]
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
BANGKOK = ZoneInfo("Asia/Bangkok")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # `.env.local` is supported for the developer workflow used by this
        # project. It is loaded after `.env`, so a local non-committed value can
        # override safe defaults without ever entering frontend code.
        env_file=(
            WORKSPACE_ROOT / ".env.local",
            PROJECT_ROOT / ".env",
            PROJECT_ROOT / ".env.local",
        ),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    setsmart_listed_data_mode: Literal["fixture", "live"] = "fixture"
    setsmart_api_key: str = ""
    setsmart_base_url: str = "https://www.setsmart.com/api/listed-company-api"
    setsmart_timeout_ms: int = 8000
    setsmart_cache_ttl_ms: int = 900_000
    setsmart_max_retries: int = 2
    setsmart_retry_base_ms: int = 250
    setsmart_stale_after_days: int = 10

    rm_as_of_date: str = ""
    rm_id: str = "RM001"
    # Daily review is a screening capacity, not a contact target.  The full
    # client book is still evaluated; this controls the concise candidate set
    # prepared for the RM workstation.
    rm_daily_review_limit: int = 48
    rm_daily_care_review_limit: int = 37
    rm_top_attention_limit: int = 5

    @property
    def as_of(self) -> date:
        """Business date the modules evaluate against."""
        if self.rm_as_of_date:
            return date.fromisoformat(self.rm_as_of_date)
        return datetime.now(BANGKOK).date()

    @property
    def live_enabled(self) -> bool:
        """Live mode needs both the flag and a key, or we fail closed to fixture."""
        return self.setsmart_listed_data_mode == "live" and bool(self.setsmart_api_key)

    def public_status(self) -> dict:
        """Safe to expose over HTTP. Never includes the key itself."""
        return {
            "setsmart_mode": self.setsmart_listed_data_mode,
            "setsmart_key_present": bool(self.setsmart_api_key),
            "setsmart_effective_mode": "live" if self.live_enabled else "fixture",
            "as_of": self.as_of.isoformat(),
            "rm_id": self.rm_id,
            "daily_review_limit": self.rm_daily_review_limit,
            "daily_care_review_limit": self.rm_daily_care_review_limit,
            "top_attention_limit": self.rm_top_attention_limit,
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
