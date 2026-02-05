from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum

from src.core.config import TurtleConfig
from src.core.logger import get_logger

logger = get_logger(__name__)


class BreakoutType(str, Enum):
    ENTRY_S1 = "ENTRY_S1"
    ENTRY_S2 = "ENTRY_S2"
    EXIT_S1 = "EXIT_S1"
    EXIT_S2 = "EXIT_S2"
    NONE = "NONE"


@dataclass
class BreakoutResult:
    breakout_type: BreakoutType
    price: Decimal
    breakout_level: Decimal | None
    system: int | None
    is_entry: bool
    is_exit: bool


class BreakoutDetector:
    def __init__(self, config: TurtleConfig):
        self.s1_entry_period = config.system1_entry_period
        self.s1_exit_period = config.system1_exit_period
        self.s2_entry_period = config.system2_entry_period
        self.s2_exit_period = config.system2_exit_period

    def get_high_low(
        self,
        prices: list[Decimal],
        period: int,
    ) -> tuple[Decimal, Decimal]:
        if len(prices) < period:
            period = len(prices)

        recent = prices[-period:]
        return max(recent), min(recent)

    def check_entry(
        self,
        current_price: Decimal,
        highs: list[Decimal],
        previous_s1_winner: bool = True,
    ) -> BreakoutResult:
        s1_high, _ = self.get_high_low(highs[:-1], self.s1_entry_period)
        s2_high, _ = self.get_high_low(highs[:-1], self.s2_entry_period)

        if current_price > s2_high:
            return BreakoutResult(
                breakout_type=BreakoutType.ENTRY_S2,
                price=current_price,
                breakout_level=s2_high,
                system=2,
                is_entry=True,
                is_exit=False,
            )

        if current_price > s1_high:
            if not previous_s1_winner:
                return BreakoutResult(
                    breakout_type=BreakoutType.ENTRY_S1,
                    price=current_price,
                    breakout_level=s1_high,
                    system=1,
                    is_entry=True,
                    is_exit=False,
                )

        return BreakoutResult(
            breakout_type=BreakoutType.NONE,
            price=current_price,
            breakout_level=None,
            system=None,
            is_entry=False,
            is_exit=False,
        )

    def check_exit(
        self,
        current_price: Decimal,
        lows: list[Decimal],
        entry_system: int,
    ) -> BreakoutResult:
        if entry_system == 1:
            exit_period = self.s1_exit_period
            exit_type = BreakoutType.EXIT_S1
        else:
            exit_period = self.s2_exit_period
            exit_type = BreakoutType.EXIT_S2

        _, period_low = self.get_high_low(lows[:-1], exit_period)

        if current_price < period_low:
            return BreakoutResult(
                breakout_type=exit_type,
                price=current_price,
                breakout_level=period_low,
                system=entry_system,
                is_entry=False,
                is_exit=True,
            )

        return BreakoutResult(
            breakout_type=BreakoutType.NONE,
            price=current_price,
            breakout_level=None,
            system=entry_system,
            is_entry=False,
            is_exit=False,
        )

    def get_entry_levels(
        self,
        highs: list[Decimal],
    ) -> dict[str, Decimal]:
        s1_high, _ = self.get_high_low(highs, self.s1_entry_period)
        s2_high, _ = self.get_high_low(highs, self.s2_entry_period)

        return {
            "s1_entry": s1_high,
            "s2_entry": s2_high,
        }

    def get_exit_levels(
        self,
        lows: list[Decimal],
    ) -> dict[str, Decimal]:
        _, s1_low = self.get_high_low(lows, self.s1_exit_period)
        _, s2_low = self.get_high_low(lows, self.s2_exit_period)

        return {
            "s1_exit": s1_low,
            "s2_exit": s2_low,
        }

    def check_proximity(
        self,
        current_price: Decimal,
        highs: list[Decimal],
        proximity_pct: Decimal,
        previous_s1_winner: bool = True,
    ) -> list[ProximityTarget]:
        """돌파가 근접 종목 식별. proximity_pct 이내면 감시 대상."""
        targets: list[ProximityTarget] = []
        s1_high, _ = self.get_high_low(highs[:-1], self.s1_entry_period)
        s2_high, _ = self.get_high_low(highs[:-1], self.s2_entry_period)

        if current_price <= s2_high:
            distance = (s2_high - current_price) / s2_high
            if distance <= proximity_pct:
                targets.append(
                    ProximityTarget(
                        breakout_level=s2_high,
                        system=2,
                        distance_pct=distance,
                    )
                )

        if not previous_s1_winner and current_price <= s1_high:
            distance = (s1_high - current_price) / s1_high
            if distance <= proximity_pct:
                targets.append(
                    ProximityTarget(
                        breakout_level=s1_high,
                        system=1,
                        distance_pct=distance,
                    )
                )

        return targets


@dataclass
class ProximityTarget:
    """돌파가 근접 감시 대상."""

    breakout_level: Decimal
    system: int
    distance_pct: Decimal


@dataclass
class WatchedStock:
    """Fast poll 감시 중인 종목."""

    stock_id: int
    symbol: str
    name: str
    targets: list[ProximityTarget]
    highs: list[Decimal]
    lows: list[Decimal]
    closes: list[Decimal]
    atr_n: Decimal
    previous_s1_winner: bool = True


class BreakoutProximityWatcher:
    """돌파 근접 종목을 초 단위로 감시하는 워처.

    1분 사이클에서 근접 종목을 식별 → register()로 등록
    fast poll 루프에서 check_and_execute()로 돌파 감지 → 즉시 진입
    """

    def __init__(self, config: TurtleConfig):
        self._config = config
        self._detector = BreakoutDetector(config)
        self._proximity_pct = Decimal(str(config.breakout_proximity_pct))
        self._watched: dict[int, WatchedStock] = {}

    @property
    def watched_symbols(self) -> list[str]:
        return [w.symbol for w in self._watched.values()]

    @property
    def watched_count(self) -> int:
        return len(self._watched)

    @property
    def has_targets(self) -> bool:
        return len(self._watched) > 0

    def register(self, stock: WatchedStock) -> None:
        self._watched[stock.stock_id] = stock
        logger.info(
            "proximity_watch_registered",
            symbol=stock.symbol,
            stock_id=stock.stock_id,
            targets=len(stock.targets),
            closest_pct=float(min(t.distance_pct for t in stock.targets)),
        )

    def unregister(self, stock_id: int) -> None:
        if stock_id in self._watched:
            symbol = self._watched[stock_id].symbol
            del self._watched[stock_id]
            logger.info("proximity_watch_removed", symbol=symbol, stock_id=stock_id)

    def clear(self) -> None:
        self._watched.clear()

    def check_breakout(
        self,
        stock_id: int,
        current_price: Decimal,
    ) -> BreakoutResult | None:
        watched = self._watched.get(stock_id)
        if not watched:
            return None

        result = self._detector.check_entry(
            current_price,
            watched.highs,
            watched.previous_s1_winner,
        )

        if result.is_entry:
            self.unregister(stock_id)
            return result

        still_near = self._detector.check_proximity(
            current_price,
            watched.highs,
            self._proximity_pct,
            watched.previous_s1_winner,
        )
        if not still_near:
            logger.info(
                "proximity_watch_expired",
                symbol=watched.symbol,
                stock_id=stock_id,
                price=float(current_price),
                reason="moved_away_from_breakout",
            )
            self.unregister(stock_id)

        return None

    def get_watched_list(self) -> list[WatchedStock]:
        return list(self._watched.values())
