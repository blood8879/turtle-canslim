from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Sequence

from sqlalchemy import and_, desc, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.data.models import (
    CANSLIMScore,
    DailyPrice,
    Fundamental,
    Order,
    Position,
    PositionStatus,
    Signal,
    Stock,
    UnitAllocation,
)

if TYPE_CHECKING:
    pass


class StockRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_symbol(self, symbol: str) -> Stock | None:
        stmt = select(Stock).where(Stock.symbol == symbol)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id(self, stock_id: int) -> Stock | None:
        stmt = select(Stock).where(Stock.id == stock_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    _MARKET_GROUPS: dict[str, list[str]] = {
        "krx": ["KOSPI", "KOSDAQ", "krx"],
        "us": ["NYSE", "NASDAQ", "US", "us"],
        "both": ["KOSPI", "KOSDAQ", "krx", "NYSE", "NASDAQ", "US", "us"],
    }

    async def get_all_active(self, market: str | None = None) -> Sequence[Stock]:
        stmt = select(Stock).where(Stock.is_active == True)
        if market:
            market_lower = market.lower()
            if market_lower in self._MARKET_GROUPS:
                stmt = stmt.where(Stock.market.in_(self._MARKET_GROUPS[market_lower]))
            else:
                stmt = stmt.where(Stock.market == market)
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def create(
        self,
        symbol: str,
        name: str,
        market: str,
        sector: str | None = None,
        industry: str | None = None,
    ) -> Stock:
        stock = Stock(
            symbol=symbol,
            name=name,
            market=market,
            sector=sector,
            industry=industry,
        )
        self._session.add(stock)
        await self._session.flush()
        return stock

    async def get_or_create(
        self,
        symbol: str,
        name: str,
        market: str,
        sector: str | None = None,
        industry: str | None = None,
    ) -> Stock:
        existing = await self.get_by_symbol(symbol)
        if existing:
            return existing
        return await self.create(symbol, name, market, sector, industry)

    async def update_fetched_period(
        self,
        stock_id: int,
        period: int,
        fetched_at: datetime | None = None,
    ) -> None:
        """Update the last_fetched_period for a stock.

        Args:
            stock_id: The stock ID to update.
            period: YYYYQ format (e.g., 20251 = 2025 Q1, 20244 = 2024 Q4).
            fetched_at: Timestamp of when the data was fetched. Defaults to now.
        """
        stmt = select(Stock).where(Stock.id == stock_id)
        result = await self._session.execute(stmt)
        stock = result.scalar_one_or_none()
        if stock:
            stock.last_fetched_period = period
            stock.last_fetched_at = fetched_at or datetime.utcnow()
            await self._session.flush()


class DailyPriceRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_latest(self, stock_id: int, limit: int = 1) -> Sequence[DailyPrice]:
        stmt = (
            select(DailyPrice)
            .where(DailyPrice.stock_id == stock_id)
            .order_by(desc(DailyPrice.date))
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def get_range(
        self,
        stock_id: int,
        start_date: datetime,
        end_date: datetime,
    ) -> Sequence[DailyPrice]:
        stmt = (
            select(DailyPrice)
            .where(
                and_(
                    DailyPrice.stock_id == stock_id,
                    DailyPrice.date >= start_date,
                    DailyPrice.date <= end_date,
                )
            )
            .order_by(DailyPrice.date)
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def get_period(self, stock_id: int, days: int) -> Sequence[DailyPrice]:
        stmt = (
            select(DailyPrice)
            .where(DailyPrice.stock_id == stock_id)
            .order_by(desc(DailyPrice.date))
            .limit(days)
        )
        result = await self._session.execute(stmt)
        prices = result.scalars().all()
        return list(reversed(prices))

    async def bulk_create(self, stock_id: int, prices: list[dict]) -> int:
        """Bulk insert prices with duplicate-safe upsert (ON CONFLICT DO NOTHING).

        Returns the number of rows actually inserted.
        """
        if not prices:
            return 0

        rows = [
            {
                "stock_id": stock_id,
                "date": p["date"],
                "open": Decimal(str(p["open"])),
                "high": Decimal(str(p["high"])),
                "low": Decimal(str(p["low"])),
                "close": Decimal(str(p["close"])),
                "volume": p["volume"],
            }
            for p in prices
        ]

        stmt = (
            pg_insert(DailyPrice)
            .values(rows)
            .on_conflict_do_nothing(constraint="uq_daily_price_stock_date")
        )
        result = await self._session.execute(stmt)
        await self._session.flush()
        return getattr(result, "rowcount", len(rows))


class FundamentalRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_latest_annual(self, stock_id: int, years: int = 5) -> Sequence[Fundamental]:
        stmt = (
            select(Fundamental)
            .where(
                and_(
                    Fundamental.stock_id == stock_id,
                    Fundamental.fiscal_quarter == None,
                )
            )
            .order_by(desc(Fundamental.fiscal_year))
            .limit(years)
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def get_quarterly(
        self,
        stock_id: int,
        year: int,
        quarter: int,
    ) -> Fundamental | None:
        stmt = select(Fundamental).where(
            and_(
                Fundamental.stock_id == stock_id,
                Fundamental.fiscal_year == year,
                Fundamental.fiscal_quarter == quarter,
            )
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_latest_period(
        self,
        stock_ids: Sequence[int] | None = None,
    ) -> tuple[int, int | None] | None:
        stmt = select(
            func.max(Fundamental.fiscal_year),
            func.max(Fundamental.fiscal_quarter),
        )
        if stock_ids is not None:
            stmt = stmt.where(Fundamental.stock_id.in_(stock_ids))
        result = await self._session.execute(stmt)
        row = result.one_or_none()
        if row is None or row[0] is None:
            return None
        return (row[0], row[1])

    async def get_latest_quarterly(self, stock_id: int) -> Fundamental | None:
        stmt = (
            select(Fundamental)
            .where(
                and_(
                    Fundamental.stock_id == stock_id,
                    Fundamental.fiscal_quarter != None,
                )
            )
            .order_by(
                desc(Fundamental.fiscal_year),
                desc(Fundamental.fiscal_quarter),
            )
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_yoy_comparison(
        self,
        stock_id: int,
        year: int,
        quarter: int,
    ) -> tuple[Fundamental | None, Fundamental | None]:
        current = await self.get_quarterly(stock_id, year, quarter)
        previous = await self.get_quarterly(stock_id, year - 1, quarter)
        return current, previous

    async def create(
        self,
        stock_id: int,
        fiscal_year: int,
        fiscal_quarter: int | None = None,
        **data: Decimal | None,
    ) -> Fundamental:
        fundamental = Fundamental(
            stock_id=stock_id,
            fiscal_year=fiscal_year,
            fiscal_quarter=fiscal_quarter,
            **data,
        )
        self._session.add(fundamental)
        await self._session.flush()
        return fundamental

    async def upsert(
        self,
        stock_id: int,
        fiscal_year: int,
        fiscal_quarter: int | None = None,
        **data: Decimal | None,
    ) -> None:
        values = {
            "stock_id": stock_id,
            "fiscal_year": fiscal_year,
            "fiscal_quarter": fiscal_quarter,
            **data,
        }
        stmt = (
            pg_insert(Fundamental)
            .values(values)
            .on_conflict_do_update(
                constraint="uq_fundamental_stock_period",
                set_={k: v for k, v in data.items() if v is not None},
            )
        )
        await self._session.execute(stmt)
        await self._session.flush()


class CANSLIMScoreRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_latest(self, stock_id: int) -> CANSLIMScore | None:
        stmt = (
            select(CANSLIMScore)
            .where(CANSLIMScore.stock_id == stock_id)
            .order_by(desc(CANSLIMScore.date))
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_stock_date(self, stock_id: int, date: datetime) -> CANSLIMScore | None:
        stmt = select(CANSLIMScore).where(
            and_(
                CANSLIMScore.stock_id == stock_id,
                CANSLIMScore.date == date,
            )
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    _MARKET_GROUPS: dict[str, list[str]] = {
        "krx": ["KOSPI", "KOSDAQ", "krx"],
        "us": ["NYSE", "NASDAQ", "US", "us"],
        "both": ["KOSPI", "KOSDAQ", "krx", "NYSE", "NASDAQ", "US", "us"],
    }

    async def get_candidates(self, min_score: int = 4, market: str | None = None) -> Sequence[CANSLIMScore]:
        stmt = (
            select(CANSLIMScore)
            .where(
                and_(
                    CANSLIMScore.is_candidate == True,
                    CANSLIMScore.total_score >= min_score,
                )
            )
            .order_by(desc(CANSLIMScore.date), desc(CANSLIMScore.total_score))
        )
        if market:
            market_lower = market.lower()
            if market_lower in self._MARKET_GROUPS:
                stmt = stmt.join(Stock, CANSLIMScore.stock_id == Stock.id).where(
                    Stock.market.in_(self._MARKET_GROUPS[market_lower])
                )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def create(self, stock_id: int, date: datetime, **scores: bool | int | Decimal | None) -> CANSLIMScore:
        score = CANSLIMScore(stock_id=stock_id, date=date, **scores)
        self._session.add(score)
        await self._session.flush()
        return score

    async def update(self, score_id: int, **fields: bool | int | Decimal | None) -> None:
        stmt = select(CANSLIMScore).where(CANSLIMScore.id == score_id)
        result = await self._session.execute(stmt)
        score = result.scalar_one_or_none()
        if score:
            for key, value in fields.items():
                setattr(score, key, value)
            await self._session.flush()


class SignalRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_pending(self) -> Sequence[Signal]:
        stmt = (
            select(Signal)
            .where(Signal.is_executed == False)
            .order_by(Signal.timestamp)
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def get_recent(self, limit: int = 50) -> Sequence[Signal]:
        """Get recent signals ordered by timestamp descending."""
        stmt = (
            select(Signal)
            .order_by(desc(Signal.timestamp))
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def get_by_stock(
        self,
        stock_id: int,
        start_date: datetime | None = None,
    ) -> Sequence[Signal]:
        stmt = select(Signal).where(Signal.stock_id == stock_id)
        if start_date:
            stmt = stmt.where(Signal.timestamp >= start_date)
        stmt = stmt.order_by(desc(Signal.timestamp))
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def create(
        self,
        stock_id: int,
        timestamp: datetime,
        signal_type: str,
        price: Decimal,
        system: int | None = None,
        atr_n: Decimal | None = None,
    ) -> Signal:
        signal = Signal(
            stock_id=stock_id,
            timestamp=timestamp,
            signal_type=signal_type,
            price=price,
            system=system,
            atr_n=atr_n,
        )
        self._session.add(signal)
        await self._session.flush()
        return signal

    async def mark_executed(self, signal_id: int) -> None:
        stmt = select(Signal).where(Signal.id == signal_id)
        result = await self._session.execute(stmt)
        signal = result.scalar_one_or_none()
        if signal:
            signal.is_executed = True
            await self._session.flush()


class PositionRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_open_positions(self) -> Sequence[Position]:
        stmt = (
            select(Position)
            .where(Position.status == PositionStatus.OPEN.value)
            .order_by(Position.entry_date)
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def get_by_stock(self, stock_id: int, open_only: bool = True) -> Position | None:
        stmt = select(Position).where(Position.stock_id == stock_id)
        if open_only:
            stmt = stmt.where(Position.status == PositionStatus.OPEN.value)
        stmt = stmt.order_by(desc(Position.entry_date)).limit(1)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_total_units(self) -> int:
        stmt = select(Position).where(Position.status == PositionStatus.OPEN.value)
        result = await self._session.execute(stmt)
        positions = result.scalars().all()
        return sum(p.units for p in positions)

    async def get_stock_units(self, stock_id: int) -> int:
        position = await self.get_by_stock(stock_id, open_only=True)
        return position.units if position else 0

    async def create(
        self,
        stock_id: int,
        entry_date: datetime,
        entry_price: Decimal,
        quantity: int,
        entry_system: int | None = None,
        stop_loss_price: Decimal | None = None,
        stop_loss_type: str | None = None,
    ) -> Position:
        position = Position(
            stock_id=stock_id,
            entry_date=entry_date,
            entry_price=entry_price,
            quantity=quantity,
            entry_system=entry_system,
            stop_loss_price=stop_loss_price,
            stop_loss_type=stop_loss_type,
        )
        self._session.add(position)
        await self._session.flush()
        return position

    async def close_position(
        self,
        position_id: int,
        exit_date: datetime,
        exit_price: Decimal,
        exit_reason: str,
    ) -> Position | None:
        stmt = select(Position).where(Position.id == position_id)
        result = await self._session.execute(stmt)
        position = result.scalar_one_or_none()

        if position:
            position.status = PositionStatus.CLOSED.value
            position.exit_date = exit_date
            position.exit_price = exit_price
            position.exit_reason = exit_reason

            pnl = (exit_price - position.entry_price) * position.quantity
            pnl_percent = (exit_price - position.entry_price) / position.entry_price
            position.pnl = pnl
            position.pnl_percent = pnl_percent

            await self._session.flush()

        return position

    async def add_pyramid_unit(
        self,
        position_id: int,
        additional_quantity: int,
        additional_price: Decimal,
    ) -> Position | None:
        stmt = select(Position).where(Position.id == position_id)
        result = await self._session.execute(stmt)
        position = result.scalar_one_or_none()

        if position:
            total_cost = (position.entry_price * position.quantity) + (
                additional_price * additional_quantity
            )
            new_quantity = position.quantity + additional_quantity
            position.entry_price = total_cost / new_quantity
            position.quantity = new_quantity
            position.units += 1
            await self._session.flush()

        return position


class OrderRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_pending(self) -> Sequence[Order]:
        stmt = (
            select(Order)
            .where(Order.status == "PENDING")
            .order_by(Order.created_at)
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def get_by_broker_id(self, broker_order_id: str) -> Order | None:
        stmt = select(Order).where(Order.broker_order_id == broker_order_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(
        self,
        stock_id: int,
        order_type: str,
        order_method: str,
        quantity: int,
        price: Decimal | None = None,
        position_id: int | None = None,
    ) -> Order:
        order = Order(
            stock_id=stock_id,
            order_type=order_type,
            order_method=order_method,
            quantity=quantity,
            price=price,
            position_id=position_id,
        )
        self._session.add(order)
        await self._session.flush()
        return order

    async def update_status(
        self,
        order_id: int,
        status: str,
        broker_order_id: str | None = None,
        filled_quantity: int | None = None,
        filled_price: Decimal | None = None,
        filled_at: datetime | None = None,
    ) -> Order | None:
        stmt = select(Order).where(Order.id == order_id)
        result = await self._session.execute(stmt)
        order = result.scalar_one_or_none()

        if order:
            order.status = status
            if broker_order_id:
                order.broker_order_id = broker_order_id
            if filled_quantity is not None:
                order.filled_quantity = filled_quantity
            if filled_price is not None:
                order.filled_price = filled_price
            if filled_at:
                order.filled_at = filled_at
            await self._session.flush()

        return order


class UnitAllocationRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_latest(self) -> UnitAllocation | None:
        stmt = select(UnitAllocation).order_by(desc(UnitAllocation.date)).limit(1)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(
        self,
        date: datetime,
        total_units: int,
        available_units: int,
        sector_allocations: str | None = None,
    ) -> UnitAllocation:
        allocation = UnitAllocation(
            date=date,
            total_units=total_units,
            available_units=available_units,
            sector_allocations=sector_allocations,
        )
        self._session.add(allocation)
        await self._session.flush()
        return allocation
