#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from src.core.config import get_settings
from src.core.logger import configure_logging, get_logger
from src.signals.atr import ATRCalculator
from src.signals.breakout import BreakoutDetector, BreakoutType
from src.signals.pyramid import PyramidManager
from src.risk.position_sizing import PositionSizer
from src.risk.stop_loss import StopLossCalculator

logger = get_logger(__name__)


@dataclass
class BacktestPosition:
    symbol: str
    entry_date: datetime
    entry_price: Decimal
    quantity: int
    units: int
    stop_loss: Decimal
    system: int
    exit_date: datetime | None = None
    exit_price: Decimal | None = None
    exit_reason: str | None = None
    pnl: Decimal = Decimal("0")
    pnl_pct: Decimal = Decimal("0")


@dataclass
class BacktestTrade:
    symbol: str
    entry_date: datetime
    exit_date: datetime
    entry_price: Decimal
    exit_price: Decimal
    quantity: int
    units: int
    pnl: Decimal
    pnl_pct: Decimal
    exit_reason: str
    holding_days: int


@dataclass
class BacktestResult:
    start_date: datetime
    end_date: datetime
    initial_capital: Decimal
    final_capital: Decimal
    total_return: Decimal
    total_return_pct: Decimal
    cagr: Decimal
    max_drawdown: Decimal
    max_drawdown_pct: Decimal
    sharpe_ratio: Decimal
    win_rate: Decimal
    profit_factor: Decimal
    total_trades: int
    winning_trades: int
    losing_trades: int
    avg_win: Decimal
    avg_loss: Decimal
    avg_holding_days: float
    trades: list[BacktestTrade] = field(default_factory=list)


class Backtester:
    def __init__(
        self,
        initial_capital: Decimal = Decimal("100000000"),
        commission_rate: Decimal = Decimal("0.00015"),
    ):
        self._settings = get_settings()
        self._initial_capital = initial_capital
        self._commission_rate = commission_rate

        self._atr_calc = ATRCalculator(self._settings.turtle)
        self._breakout = BreakoutDetector(self._settings.turtle)
        self._pyramid = PyramidManager(self._settings.turtle, self._settings.risk)
        self._position_sizer = PositionSizer(self._settings.risk)
        self._stop_loss_calc = StopLossCalculator(self._settings.risk)

    def run(
        self,
        price_data: dict[str, list[dict]],
        start_date: datetime,
        end_date: datetime,
    ) -> BacktestResult:
        logger.info(
            "backtest_start",
            symbols=len(price_data),
            start=start_date.isoformat(),
            end=end_date.isoformat(),
        )

        capital = self._initial_capital
        positions: dict[str, BacktestPosition] = {}
        trades: list[BacktestTrade] = []
        equity_curve: list[Decimal] = [capital]
        max_equity = capital
        max_drawdown = Decimal("0")

        all_dates = set()
        for prices in price_data.values():
            for p in prices:
                if start_date <= p["date"] <= end_date:
                    all_dates.add(p["date"])

        sorted_dates = sorted(all_dates)

        for current_date in sorted_dates:
            for symbol, open_pos in list(positions.items()):
                if symbol not in price_data:
                    continue

                prices = [p for p in price_data[symbol] if p["date"] <= current_date]
                if len(prices) < 2:
                    continue

                current_price = Decimal(str(prices[-1]["close"]))

                if current_price <= open_pos.stop_loss:
                    pnl = (current_price - open_pos.entry_price) * open_pos.quantity
                    commission = current_price * open_pos.quantity * self._commission_rate
                    pnl -= commission

                    capital += (current_price * open_pos.quantity) + pnl

                    trades.append(BacktestTrade(
                        symbol=symbol,
                        entry_date=open_pos.entry_date,
                        exit_date=current_date,
                        entry_price=open_pos.entry_price,
                        exit_price=current_price,
                        quantity=open_pos.quantity,
                        units=open_pos.units,
                        pnl=pnl,
                        pnl_pct=(current_price - open_pos.entry_price) / open_pos.entry_price,
                        exit_reason="STOP_LOSS",
                        holding_days=(current_date - open_pos.entry_date).days,
                    ))

                    del positions[symbol]
                    continue

                lows = [Decimal(str(p["low"])) for p in prices]
                exit_period = 10 if open_pos.system == 1 else 20

                if len(lows) >= exit_period:
                    exit_level = min(lows[-exit_period:-1]) if len(lows) > exit_period else min(lows[:-1])

                    if current_price < exit_level:
                        pnl = (current_price - open_pos.entry_price) * open_pos.quantity
                        commission = current_price * open_pos.quantity * self._commission_rate
                        pnl -= commission

                        capital += (current_price * open_pos.quantity) + pnl

                        trades.append(BacktestTrade(
                            symbol=symbol,
                            entry_date=open_pos.entry_date,
                            exit_date=current_date,
                            entry_price=open_pos.entry_price,
                            exit_price=current_price,
                            quantity=open_pos.quantity,
                            units=open_pos.units,
                            pnl=pnl,
                            pnl_pct=(current_price - open_pos.entry_price) / open_pos.entry_price,
                            exit_reason=f"EXIT_S{open_pos.system}",
                            holding_days=(current_date - open_pos.entry_date).days,
                        ))

                        del positions[symbol]

            total_units = sum(p.units for p in positions.values())

            if total_units < self._settings.risk.max_units_total:
                for symbol, prices_list in price_data.items():
                    if symbol in positions:
                        continue

                    prices = [p for p in prices_list if p["date"] <= current_date]
                    if len(prices) < 56:
                        continue

                    highs = [Decimal(str(p["high"])) for p in prices]
                    lows = [Decimal(str(p["low"])) for p in prices]
                    closes = [Decimal(str(p["close"])) for p in prices]
                    current_price = closes[-1]

                    atr_result = self._atr_calc.calculate(highs, lows, closes)
                    if not atr_result:
                        continue

                    s1_high = max(highs[-21:-1])
                    s2_high = max(highs[-56:-1])

                    entry_system = None
                    if current_price > s2_high:
                        entry_system = 2
                    elif current_price > s1_high:
                        entry_system = 1

                    if entry_system:
                        stop_result = self._stop_loss_calc.calculate_initial_stop(
                            current_price, atr_result.atr
                        )

                        position_result = self._position_sizer.calculate_full_position(
                            account_value=capital,
                            entry_price=current_price,
                            atr_n=atr_result.atr,
                        )

                        cost = current_price * position_result.quantity
                        commission = cost * self._commission_rate

                        if cost + commission <= capital * Decimal("0.95"):
                            capital -= cost + commission

                            positions[symbol] = BacktestPosition(
                                symbol=symbol,
                                entry_date=current_date,
                                entry_price=current_price,
                                quantity=position_result.quantity,
                                units=1,
                                stop_loss=stop_result.price,
                                system=entry_system,
                            )

                            total_units += 1

                            if total_units >= self._settings.risk.max_units_total:
                                break

            portfolio_value = capital
            for pos in positions.values():
                symbol_prices = [p for p in price_data.get(pos.symbol, []) if p["date"] <= current_date]
                if symbol_prices:
                    current_price = Decimal(str(symbol_prices[-1]["close"]))
                    portfolio_value += current_price * pos.quantity

            equity_curve.append(portfolio_value)

            if portfolio_value > max_equity:
                max_equity = portfolio_value

            drawdown = (max_equity - portfolio_value) / max_equity
            if drawdown > max_drawdown:
                max_drawdown = drawdown

        for symbol, pos in positions.items():
            prices = price_data.get(symbol, [])
            if prices:
                final_price = Decimal(str(prices[-1]["close"]))
                pnl = (final_price - pos.entry_price) * pos.quantity
                capital += final_price * pos.quantity

                trades.append(BacktestTrade(
                    symbol=symbol,
                    entry_date=pos.entry_date,
                    exit_date=end_date,
                    entry_price=pos.entry_price,
                    exit_price=final_price,
                    quantity=pos.quantity,
                    units=pos.units,
                    pnl=pnl,
                    pnl_pct=(final_price - pos.entry_price) / pos.entry_price,
                    exit_reason="END_OF_BACKTEST",
                    holding_days=(end_date - pos.entry_date).days,
                ))

        total_return = capital - self._initial_capital
        total_return_pct = total_return / self._initial_capital

        years = (end_date - start_date).days / 365.25
        cagr = ((capital / self._initial_capital) ** (Decimal("1") / Decimal(str(years)))) - 1 if years > 0 else Decimal("0")

        winning_trades = [t for t in trades if t.pnl > 0]
        losing_trades = [t for t in trades if t.pnl <= 0]

        win_rate = Decimal(str(len(winning_trades))) / Decimal(str(len(trades))) if trades else Decimal("0")

        gross_profit = sum(t.pnl for t in winning_trades)
        gross_loss = abs(sum(t.pnl for t in losing_trades))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else Decimal("0")

        avg_win = gross_profit / len(winning_trades) if winning_trades else Decimal("0")
        avg_loss = gross_loss / len(losing_trades) if losing_trades else Decimal("0")

        avg_holding = sum(t.holding_days for t in trades) / len(trades) if trades else 0

        returns = []
        for i in range(1, len(equity_curve)):
            ret = (equity_curve[i] - equity_curve[i-1]) / equity_curve[i-1]
            returns.append(float(ret))

        if returns:
            import statistics
            avg_return = statistics.mean(returns)
            std_return = statistics.stdev(returns) if len(returns) > 1 else 0.0001
            sharpe = Decimal(str((avg_return * 252**0.5) / (std_return * 252**0.5))) if std_return > 0 else Decimal("0")
        else:
            sharpe = Decimal("0")

        return BacktestResult(
            start_date=start_date,
            end_date=end_date,
            initial_capital=self._initial_capital,
            final_capital=capital,
            total_return=total_return,
            total_return_pct=total_return_pct,
            cagr=cagr,
            max_drawdown=max_drawdown * self._initial_capital,
            max_drawdown_pct=max_drawdown,
            sharpe_ratio=sharpe,
            win_rate=win_rate,
            profit_factor=profit_factor,
            total_trades=len(trades),
            winning_trades=len(winning_trades),
            losing_trades=len(losing_trades),
            avg_win=avg_win,
            avg_loss=avg_loss,
            avg_holding_days=avg_holding,
            trades=trades,
        )


def print_result(result: BacktestResult) -> None:
    print("\n" + "=" * 70)
    print("BACKTEST RESULTS")
    print("=" * 70)
    print(f"Period:           {result.start_date.strftime('%Y-%m-%d')} to {result.end_date.strftime('%Y-%m-%d')}")
    print(f"Initial Capital:  {result.initial_capital:>15,.0f}")
    print(f"Final Capital:    {result.final_capital:>15,.0f}")
    print("-" * 70)
    print(f"Total Return:     {result.total_return:>+15,.0f} ({result.total_return_pct:+.2%})")
    print(f"CAGR:             {result.cagr:>+15.2%}")
    print(f"Max Drawdown:     {result.max_drawdown:>15,.0f} ({result.max_drawdown_pct:.2%})")
    print(f"Sharpe Ratio:     {result.sharpe_ratio:>15.2f}")
    print("-" * 70)
    print(f"Total Trades:     {result.total_trades:>15}")
    print(f"Winning Trades:   {result.winning_trades:>15}")
    print(f"Losing Trades:    {result.losing_trades:>15}")
    print(f"Win Rate:         {result.win_rate:>15.2%}")
    print(f"Profit Factor:    {result.profit_factor:>15.2f}")
    print("-" * 70)
    print(f"Avg Win:          {result.avg_win:>+15,.0f}")
    print(f"Avg Loss:         {result.avg_loss:>15,.0f}")
    print(f"Avg Holding Days: {result.avg_holding_days:>15.1f}")
    print("=" * 70)

    if result.trades:
        print("\nRecent Trades:")
        print(f"{'Symbol':<10} {'Entry':<12} {'Exit':<12} {'P&L':>12} {'P&L%':>8} {'Reason':<15}")
        print("-" * 70)

        for trade in result.trades[-10:]:
            print(
                f"{trade.symbol:<10} "
                f"{trade.entry_date.strftime('%Y-%m-%d'):<12} "
                f"{trade.exit_date.strftime('%Y-%m-%d'):<12} "
                f"{trade.pnl:>+12,.0f} "
                f"{trade.pnl_pct:>+7.2%} "
                f"{trade.exit_reason:<15}"
            )

    print()


def generate_sample_data(
    symbols: list[str],
    start_date: datetime,
    end_date: datetime,
) -> dict[str, list[dict]]:
    import random

    data: dict[str, list[dict]] = {}

    for symbol in symbols:
        prices = []
        current_date = start_date
        price = random.uniform(10000, 100000)

        while current_date <= end_date:
            if current_date.weekday() < 5:
                change = random.gauss(0.0005, 0.02)
                price *= (1 + change)

                high = price * (1 + abs(random.gauss(0, 0.01)))
                low = price * (1 - abs(random.gauss(0, 0.01)))
                open_price = price * (1 + random.gauss(0, 0.005))

                prices.append({
                    "date": current_date,
                    "open": open_price,
                    "high": max(high, open_price, price),
                    "low": min(low, open_price, price),
                    "close": price,
                    "volume": random.randint(100000, 10000000),
                })

            current_date += timedelta(days=1)

        data[symbol] = prices

    return data


def main() -> None:
    parser = argparse.ArgumentParser(description="Run backtest")
    parser.add_argument(
        "--start",
        "-s",
        type=str,
        default=(datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d"),
        help="Start date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--end",
        "-e",
        type=str,
        default=datetime.now().strftime("%Y-%m-%d"),
        help="End date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--capital",
        "-c",
        type=float,
        default=100000000,
        help="Initial capital (default: 100,000,000)",
    )
    parser.add_argument(
        "--sample",
        action="store_true",
        help="Use sample data for demonstration",
    )
    parser.add_argument(
        "--log-level",
        "-l",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Log level",
    )

    args = parser.parse_args()

    configure_logging(level=args.log_level)

    start_date = datetime.strptime(args.start, "%Y-%m-%d")
    end_date = datetime.strptime(args.end, "%Y-%m-%d")

    print(f"\nBacktest Configuration:")
    print(f"  Period: {args.start} to {args.end}")
    print(f"  Capital: {args.capital:,.0f}")

    if args.sample:
        print("  Data: Sample (randomly generated)\n")
        symbols = ["005930", "000660", "035720", "035420", "051910"]
        price_data = generate_sample_data(symbols, start_date, end_date)
    else:
        print("  Data: Database (requires data import)\n")
        print("Note: Run with --sample to use generated data for testing.")
        price_data = {}

    if not price_data:
        print("No price data available. Use --sample for demonstration.")
        sys.exit(0)

    backtester = Backtester(initial_capital=Decimal(str(args.capital)))
    result = backtester.run(price_data, start_date, end_date)

    print_result(result)


if __name__ == "__main__":
    main()
