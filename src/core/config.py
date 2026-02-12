from __future__ import annotations

from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class TradingMode(str, Enum):
    PAPER = "paper"
    LIVE = "live"


class Market(str, Enum):
    KRX = "krx"
    US = "us"
    BOTH = "both"


class CANSLIMConfig(BaseModel):
    c_eps_growth_min: float = Field(default=0.20, ge=0, le=1)
    c_revenue_growth_min: float = Field(default=0.25, ge=0, le=1)
    a_eps_growth_min: float = Field(default=0.20, ge=0, le=1)
    a_min_years: int = Field(default=2, ge=1, le=10)
    l_rs_min: int = Field(default=80, ge=1, le=99)
    i_institution_min: float = Field(default=0.10, ge=0, le=1)
    min_roe: float = Field(default=0.12, ge=0, le=1)


class TurtleConfig(BaseModel):
    system1_entry_period: int = Field(default=20, ge=5, le=100)
    system1_exit_period: int = Field(default=10, ge=5, le=100)
    system2_entry_period: int = Field(default=55, ge=20, le=200)
    system2_exit_period: int = Field(default=20, ge=10, le=100)
    atr_period: int = Field(default=20, ge=5, le=50)
    pyramid_unit_interval: float = Field(default=0.5, ge=0.25, le=1.0)
    signal_check_interval_minutes: int = Field(default=1, ge=1, le=30)
    breakout_proximity_pct: float = Field(default=0.03, ge=0.005, le=0.10)
    fast_poll_interval_seconds: int = Field(default=3, ge=1, le=30)


class RiskConfig(BaseModel):
    risk_per_unit: float = Field(default=0.02, ge=0.005, le=0.05)
    max_units_per_stock: int = Field(default=4, ge=1, le=10)
    max_units_correlated: int = Field(default=10, ge=4, le=20)
    max_units_loosely_correlated: int = Field(default=16, ge=6, le=30)
    max_units_total: int = Field(default=20, ge=10, le=50)
    stop_loss_atr_multiplier: float = Field(default=2.0, ge=1.0, le=4.0)
    stop_loss_max_percent: float = Field(default=0.08, ge=0.03, le=0.15)
    max_entry_slippage_pct: float = Field(default=0.015, ge=0.005, le=0.05)
    max_exit_slippage_pct: float = Field(default=0.03, ge=0.01, le=0.10)


class ScheduleConfig(BaseModel):
    class MarketSchedule(BaseModel):
        premarket_time: str = "08:00"
        screening_time: str = "08:00"
        market_open: str = "09:00"
        market_close: str = "15:30"

    krx: MarketSchedule = Field(default_factory=lambda: ScheduleConfig.MarketSchedule())
    us: MarketSchedule = Field(
        default_factory=lambda: ScheduleConfig.MarketSchedule(
            premarket_time="22:30",
            screening_time="22:30",
            market_open="23:30",
            market_close="06:00",
        )
    )


class NotificationConfig(BaseModel):
    telegram_enabled: bool = False
    notify_on_signal: bool = True
    notify_on_order: bool = True
    notify_on_fill: bool = True
    daily_report: bool = True


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
    )

    trading_mode: TradingMode = TradingMode.PAPER
    market: Market = Market.KRX

    kis_paper_app_key: str = ""
    kis_paper_app_secret: str = ""
    kis_paper_account: str = ""
    kis_live_app_key: str = ""
    kis_live_app_secret: str = ""
    kis_live_account: str = ""
    dart_api_key: str = ""

    # SEC EDGAR (no API key required, but User-Agent is mandatory)
    sec_user_agent: str = "TurtleCANSLIM contact@example.com"

    database_url: str = "postgresql://localhost:5432/turtle_canslim"
    redis_url: str = ""

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    canslim: CANSLIMConfig = Field(default_factory=CANSLIMConfig)
    turtle: TurtleConfig = Field(default_factory=TurtleConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
    notification: NotificationConfig = Field(default_factory=NotificationConfig)

    @model_validator(mode="before")
    @classmethod
    def load_yaml_config(cls, data: dict[str, Any]) -> dict[str, Any]:
        config_path = Path("config/settings.yaml")
        if config_path.exists():
            with open(config_path, encoding="utf-8") as f:
                yaml_config = yaml.safe_load(f) or {}
            for key, value in yaml_config.items():
                if key not in data or data[key] is None:
                    data[key] = value
        return data

    @model_validator(mode="after")
    def validate_live_mode_credentials(self) -> Settings:
        if self.trading_mode == TradingMode.LIVE:
            if not all([self.kis_live_app_key, self.kis_live_app_secret, self.kis_live_account]):
                raise ValueError(
                    "LIVE mode requires KIS_LIVE_APP_KEY, KIS_LIVE_APP_SECRET, KIS_LIVE_ACCOUNT"
                )
        return self

    @property
    def is_paper_mode(self) -> bool:
        return self.trading_mode == TradingMode.PAPER

    @property
    def is_live_mode(self) -> bool:
        return self.trading_mode == TradingMode.LIVE

    @property
    def active_kis_credentials(self) -> tuple[str, str, str]:
        if self.is_paper_mode:
            return (self.kis_paper_app_key, self.kis_paper_app_secret, self.kis_paper_account)
        return (self.kis_live_app_key, self.kis_live_app_secret, self.kis_live_account)

    @property
    def has_kis_credentials(self) -> bool:
        key, secret, account = self.active_kis_credentials
        return all([key, secret, account])


@lru_cache
def get_settings() -> Settings:
    return Settings()
