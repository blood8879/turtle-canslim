from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

if TYPE_CHECKING:
    pass


class Base(DeclarativeBase):
    pass


class MarketType(str, Enum):
    KOSPI = "KOSPI"
    KOSDAQ = "KOSDAQ"
    NYSE = "NYSE"
    NASDAQ = "NASDAQ"


class SignalType(str, Enum):
    ENTRY_S1 = "ENTRY_S1"
    ENTRY_S2 = "ENTRY_S2"
    EXIT_S1 = "EXIT_S1"
    EXIT_S2 = "EXIT_S2"
    STOP_LOSS = "STOP_LOSS"
    PYRAMID = "PYRAMID"


class OrderType(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderMethod(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    FILLED = "FILLED"
    PARTIAL = "PARTIAL"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class PositionStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class StopLossType(str, Enum):
    ATR_2N = "2N"
    PERCENT_8 = "8%"


class Stock(Base):
    __tablename__ = "stocks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    market: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    sector: Mapped[str | None] = mapped_column(String(50))
    industry: Mapped[str | None] = mapped_column(String(50))
    shares_outstanding: Mapped[int | None] = mapped_column(Integer)
    institutional_ownership: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    institutional_count: Mapped[int | None] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, onupdate=datetime.utcnow)

    # Earnings tracking - Period-based freshness detection
    # last_fetched_period: YYYYQ format (e.g., 20251 = 2025 Q1, 20244 = 2024 Q4)
    last_fetched_period: Mapped[int | None] = mapped_column(Integer)
    last_fetched_at: Mapped[datetime | None] = mapped_column(DateTime)

    daily_prices: Mapped[list[DailyPrice]] = relationship(back_populates="stock")
    fundamentals: Mapped[list[Fundamental]] = relationship(back_populates="stock")
    canslim_scores: Mapped[list[CANSLIMScore]] = relationship(back_populates="stock")
    signals: Mapped[list[Signal]] = relationship(back_populates="stock")
    positions: Mapped[list[Position]] = relationship(back_populates="stock")
    orders: Mapped[list[Order]] = relationship(back_populates="stock")


class DailyPrice(Base):
    __tablename__ = "daily_prices"
    __table_args__ = (UniqueConstraint("stock_id", "date", name="uq_daily_price_stock_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.id"), nullable=False, index=True)
    date: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    open: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    high: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    low: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    close: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    volume: Mapped[int] = mapped_column(Integer, nullable=False)

    stock: Mapped[Stock] = relationship(back_populates="daily_prices")


class Fundamental(Base):
    __tablename__ = "fundamentals"
    __table_args__ = (
        UniqueConstraint(
            "stock_id", "fiscal_year", "fiscal_quarter", name="uq_fundamental_stock_period"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.id"), nullable=False, index=True)
    fiscal_year: Mapped[int] = mapped_column(Integer, nullable=False)
    fiscal_quarter: Mapped[int | None] = mapped_column(Integer)

    revenue: Mapped[Decimal | None] = mapped_column(Numeric(20, 2))
    operating_income: Mapped[Decimal | None] = mapped_column(Numeric(20, 2))
    net_income: Mapped[Decimal | None] = mapped_column(Numeric(20, 2))
    eps: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))

    total_assets: Mapped[Decimal | None] = mapped_column(Numeric(20, 2))
    total_equity: Mapped[Decimal | None] = mapped_column(Numeric(20, 2))

    roe: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))

    announcement_date: Mapped[datetime | None] = mapped_column(DateTime)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    stock: Mapped[Stock] = relationship(back_populates="fundamentals")


class CANSLIMScore(Base):
    __tablename__ = "canslim_scores"
    __table_args__ = (UniqueConstraint("stock_id", "date", name="uq_canslim_stock_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.id"), nullable=False, index=True)
    date: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)

    c_score: Mapped[bool | None] = mapped_column(Boolean)
    a_score: Mapped[bool | None] = mapped_column(Boolean)
    n_score: Mapped[bool | None] = mapped_column(Boolean)
    s_score: Mapped[bool | None] = mapped_column(Boolean)
    l_score: Mapped[bool | None] = mapped_column(Boolean)
    i_score: Mapped[bool | None] = mapped_column(Boolean)
    m_score: Mapped[bool | None] = mapped_column(Boolean)

    total_score: Mapped[int | None] = mapped_column(Integer)
    rs_rating: Mapped[int | None] = mapped_column(Integer)

    c_eps_growth: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    c_revenue_growth: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    a_eps_growth: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))

    is_candidate: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    stock: Mapped[Stock] = relationship(back_populates="canslim_scores")


class Signal(Base):
    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.id"), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)

    signal_type: Mapped[str] = mapped_column(String(20), nullable=False)
    system: Mapped[int | None] = mapped_column(Integer)
    price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    atr_n: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))

    is_executed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    stock: Mapped[Stock] = relationship(back_populates="signals")


class Position(Base):
    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.id"), nullable=False, index=True)

    entry_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    entry_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    entry_system: Mapped[int | None] = mapped_column(Integer)

    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    units: Mapped[int] = mapped_column(Integer, default=1)

    stop_loss_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    stop_loss_type: Mapped[str | None] = mapped_column(String(10))

    status: Mapped[str] = mapped_column(String(20), default=PositionStatus.OPEN.value, index=True)
    exit_date: Mapped[datetime | None] = mapped_column(DateTime)
    exit_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    exit_reason: Mapped[str | None] = mapped_column(String(50))

    pnl: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    pnl_percent: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, onupdate=datetime.utcnow)

    stock: Mapped[Stock] = relationship(back_populates="positions")
    orders: Mapped[list[Order]] = relationship(back_populates="position")


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    position_id: Mapped[int | None] = mapped_column(ForeignKey("positions.id"))
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.id"), nullable=False, index=True)

    order_type: Mapped[str] = mapped_column(String(10), nullable=False)
    order_method: Mapped[str] = mapped_column(String(20), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))

    status: Mapped[str] = mapped_column(String(20), default=OrderStatus.PENDING.value, index=True)
    filled_quantity: Mapped[int] = mapped_column(Integer, default=0)
    filled_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))

    broker_order_id: Mapped[str | None] = mapped_column(String(50))

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    filled_at: Mapped[datetime | None] = mapped_column(DateTime)

    position: Mapped[Position | None] = relationship(back_populates="orders")
    stock: Mapped[Stock] = relationship(back_populates="orders")


class UnitAllocation(Base):
    __tablename__ = "unit_allocations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)

    total_units: Mapped[int] = mapped_column(Integer, default=0)
    available_units: Mapped[int | None] = mapped_column(Integer)

    sector_allocations: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
