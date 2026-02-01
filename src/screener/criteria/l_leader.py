from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass
class LLeaderResult:
    passed: bool
    rs_rating: int | None
    price_vs_market: Decimal | None
    is_industry_leader: bool
    reason: str


class LLeader:
    def __init__(self, min_rs_rating: int = 80):
        self.min_rs = min_rs_rating

    def calculate_rs_rating(
        self,
        stock_returns: list[Decimal],
        market_returns: list[Decimal],
    ) -> int | None:
        if len(stock_returns) < 4 or len(market_returns) < 4:
            return None

        stock_3m = sum(stock_returns[-3:]) if len(stock_returns) >= 3 else Decimal(0)
        stock_6m = sum(stock_returns[-6:]) if len(stock_returns) >= 6 else stock_3m
        stock_9m = sum(stock_returns[-9:]) if len(stock_returns) >= 9 else stock_6m
        stock_12m = sum(stock_returns) if len(stock_returns) >= 12 else stock_9m

        weighted_return = (
            stock_3m * Decimal("0.4")
            + stock_6m * Decimal("0.2")
            + stock_9m * Decimal("0.2")
            + stock_12m * Decimal("0.2")
        )

        market_avg = sum(market_returns) / len(market_returns) if market_returns else Decimal(0)

        if market_avg == 0:
            relative_strength = weighted_return * 100
        else:
            relative_strength = (weighted_return / abs(market_avg)) * 50 + 50

        rs_rating = min(99, max(1, int(relative_strength)))

        return rs_rating

    def evaluate(
        self,
        rs_rating: int | None = None,
        stock_returns: list[Decimal] | None = None,
        market_returns: list[Decimal] | None = None,
        is_industry_leader: bool = False,
    ) -> LLeaderResult:
        if rs_rating is None and stock_returns and market_returns:
            rs_rating = self.calculate_rs_rating(stock_returns, market_returns)

        if rs_rating is None:
            return LLeaderResult(
                passed=False,
                rs_rating=None,
                price_vs_market=None,
                is_industry_leader=is_industry_leader,
                reason="Unable to calculate RS rating",
            )

        passed = rs_rating >= self.min_rs

        if passed:
            reason = f"RS Rating {rs_rating} >= {self.min_rs}"
            if is_industry_leader:
                reason += " (Industry leader)"
        else:
            reason = f"RS Rating {rs_rating} < {self.min_rs}"

        price_vs_market = None
        if stock_returns and market_returns:
            stock_total = sum(stock_returns)
            market_total = sum(market_returns)
            if market_total != 0:
                price_vs_market = stock_total - market_total

        return LLeaderResult(
            passed=passed,
            rs_rating=rs_rating,
            price_vs_market=price_vs_market,
            is_industry_leader=is_industry_leader,
            reason=reason,
        )
