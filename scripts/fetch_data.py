#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import sys
import time
from datetime import datetime, timedelta
from decimal import Decimal

from src.core.config import get_settings
from src.core.database import get_db_manager
from src.core.logger import configure_logging, get_logger
from src.data.kis_client import KISClient
from src.data.repositories import (
    DailyPriceRepository,
    StockRepository,
)

logger = get_logger(__name__)


class StockListFetcher:
    """Fetch stock lists from various markets."""

    async def fetch_krx_stocks(self, sample_size: int | None = None) -> list[dict]:
        """Fetch KRX (Korean) stock list."""
        try:
            import pykrx
        except ImportError:
            logger.error("pykrx_not_installed")
            print("Error: pykrx is not installed. Install with: pip install pykrx")
            return []

        logger.info("fetching_krx_stocks")

        try:
            from pykrx import stock

            # Get KOSPI stocks
            kospi_df = stock.get_market_ticker_list(market="KOSPI")
            kospi_stocks = []
            for ticker in kospi_df:
                try:
                    name = stock.get_market_ticker_name(ticker)
                    kospi_stocks.append({"symbol": ticker, "name": name, "market": "krx"})
                except Exception as e:
                    logger.warning("krx_ticker_info_error", ticker=ticker, error=str(e))
                    continue

            # Get KOSDAQ stocks
            kosdaq_df = stock.get_market_ticker_list(market="KOSDAQ")
            kosdaq_stocks = []
            for ticker in kosdaq_df:
                try:
                    name = stock.get_market_ticker_name(ticker)
                    kosdaq_stocks.append({"symbol": ticker, "name": name, "market": "krx"})
                except Exception as e:
                    logger.warning("kosdaq_ticker_info_error", ticker=ticker, error=str(e))
                    continue

            all_stocks = kospi_stocks + kosdaq_stocks

            if sample_size:
                all_stocks = all_stocks[:sample_size]

            logger.info(
                "krx_stocks_fetched",
                total=len(all_stocks),
                kospi=len(kospi_stocks),
                kosdaq=len(kosdaq_stocks),
            )

            return all_stocks

        except Exception as e:
            logger.error("krx_fetch_error", error=str(e))
            raise

    async def fetch_us_stocks(self, sample_size: int | None = None) -> list[dict]:
        """Fetch US stock list (simplified - top market cap stocks)."""
        logger.info("fetching_us_stocks")

        # For US stocks, we'll use a hardcoded list of major stocks
        # In production, you'd fetch from a real data source
        us_stocks = [
            {"symbol": "AAPL", "name": "Apple Inc.", "market": "us"},
            {"symbol": "MSFT", "name": "Microsoft Corporation", "market": "us"},
            {"symbol": "GOOGL", "name": "Alphabet Inc.", "market": "us"},
            {"symbol": "AMZN", "name": "Amazon.com Inc.", "market": "us"},
            {"symbol": "NVDA", "name": "NVIDIA Corporation", "market": "us"},
            {"symbol": "TSLA", "name": "Tesla Inc.", "market": "us"},
            {"symbol": "META", "name": "Meta Platforms Inc.", "market": "us"},
            {"symbol": "AVGO", "name": "Broadcom Inc.", "market": "us"},
            {"symbol": "ASML", "name": "ASML Holding N.V.", "market": "us"},
            {"symbol": "NFLX", "name": "Netflix Inc.", "market": "us"},
        ]

        if sample_size:
            us_stocks = us_stocks[:sample_size]

        logger.info("us_stocks_fetched", total=len(us_stocks))

        return us_stocks


class PriceFetcher:
    """Fetch price data for stocks."""

    def __init__(self, rate_limit_delay: float = 0.1):
        """Initialize price fetcher with rate limiting."""
        self._kis_client = KISClient()
        self._rate_limit_delay = rate_limit_delay

    async def fetch_krx_prices(
        self,
        symbol: str,
        days: int = 100,
        end_date: datetime | None = None,
    ) -> list[dict]:
        """Fetch KRX daily prices."""
        try:
            await asyncio.sleep(self._rate_limit_delay)

            prices = await self._kis_client.get_daily_prices(
                symbol=symbol,
                period=days,
                end_date=end_date,
            )

            result = [
                {
                    "date": p.date,
                    "open": p.open,
                    "high": p.high,
                    "low": p.low,
                    "close": p.close,
                    "volume": p.volume,
                }
                for p in prices
            ]

            logger.debug("krx_prices_fetched", symbol=symbol, count=len(result))
            return result

        except Exception as e:
            logger.error("krx_price_fetch_error", symbol=symbol, error=str(e))
            return []

    async def fetch_us_prices(
        self,
        symbol: str,
        days: int = 100,
        end_date: datetime | None = None,
    ) -> list[dict]:
        """Fetch US stock prices (stub for future implementation)."""
        # In production, use a data provider like yfinance or Alpha Vantage
        logger.info("us_price_fetch_stub", symbol=symbol)
        return []


class DataLoader:
    """Load fetched data into database."""

    def __init__(self):
        self._db = get_db_manager()

    async def load_stocks(self, stocks: list[dict]) -> int:
        """Load stocks into database."""
        logger.info("loading_stocks", count=len(stocks))

        loaded = 0
        try:
            async with self._db.session() as session:
                stock_repo = StockRepository(session)

                for stock_data in stocks:
                    try:
                        stock = await stock_repo.get_or_create(
                            symbol=stock_data["symbol"],
                            name=stock_data["name"],
                            market=stock_data["market"],
                        )
                        loaded += 1
                        logger.debug("stock_loaded", symbol=stock.symbol)
                    except Exception as e:
                        logger.error(
                            "stock_load_error",
                            symbol=stock_data["symbol"],
                            error=str(e),
                        )
                        continue

            logger.info("stocks_load_complete", loaded=loaded, total=len(stocks))
            return loaded

        except Exception as e:
            logger.error("stocks_load_error", error=str(e))
            raise

    async def load_prices(
        self,
        stock_symbol: str,
        prices: list[dict],
    ) -> int:
        """Load daily prices into database."""
        if not prices:
            return 0

        logger.debug("loading_prices", symbol=stock_symbol, count=len(prices))

        try:
            async with self._db.session() as session:
                stock_repo = StockRepository(session)
                price_repo = DailyPriceRepository(session)

                stock = await stock_repo.get_by_symbol(stock_symbol)
                if not stock:
                    logger.warning("stock_not_found", symbol=stock_symbol)
                    return 0

                await price_repo.bulk_create(stock.id, prices)

                logger.debug("prices_loaded", symbol=stock_symbol, count=len(prices))
                return len(prices)

        except Exception as e:
            logger.error("prices_load_error", symbol=stock_symbol, error=str(e))
            return 0


async def run_fetch_krx(days: int = 100, sample: int | None = None) -> None:
    """Fetch and load KRX market data."""
    logger.info("krx_fetch_start", days=days, sample=sample)

    # Fetch stock list
    fetcher = StockListFetcher()
    stocks = await fetcher.fetch_krx_stocks(sample_size=sample)

    if not stocks:
        logger.error("no_krx_stocks_fetched")
        print("Error: Could not fetch KRX stocks. Check pykrx installation.")
        return

    # Load stocks to database
    loader = DataLoader()
    loaded_stocks = await loader.load_stocks(stocks)

    print(f"\n{'='*60}")
    print(f"KRX Stock List Loaded")
    print(f"{'='*60}")
    print(f"Stocks loaded: {loaded_stocks}/{len(stocks)}")

    # Fetch and load prices
    price_fetcher = PriceFetcher()
    end_date = datetime.now()
    total_prices = 0

    print(f"\nFetching price data (last {days} days)...")

    try:
        for i, stock in enumerate(stocks, 1):
            symbol = stock["symbol"]
            print(f"  [{i}/{len(stocks)}] {symbol}...", end="", flush=True)

            prices = await price_fetcher.fetch_krx_prices(
                symbol=symbol,
                days=days,
                end_date=end_date,
            )

            loaded = await loader.load_prices(symbol, prices)
            total_prices += loaded

            if prices:
                print(f" ✓ ({len(prices)} days)")
            else:
                print(" ✗ (no data)")

    except KeyboardInterrupt:
        print("\n\nFetch cancelled.")
        logger.info("krx_fetch_cancelled")

    print(f"\n{'='*60}")
    print(f"Price Data Loaded")
    print(f"{'='*60}")
    print(f"Total prices loaded: {total_prices}")
    print(f"{'='*60}\n")

    logger.info("krx_fetch_complete", stocks_loaded=loaded_stocks, prices_loaded=total_prices)


async def run_fetch_us(days: int = 100, sample: int | None = None) -> None:
    """Fetch and load US market data."""
    logger.info("us_fetch_start", days=days, sample=sample)

    # Fetch stock list
    fetcher = StockListFetcher()
    stocks = await fetcher.fetch_us_stocks(sample_size=sample)

    if not stocks:
        logger.error("no_us_stocks_fetched")
        return

    # Load stocks to database
    loader = DataLoader()
    loaded_stocks = await loader.load_stocks(stocks)

    print(f"\n{'='*60}")
    print(f"US Stock List Loaded")
    print(f"{'='*60}")
    print(f"Stocks loaded: {loaded_stocks}/{len(stocks)}")

    # Price fetch for US would be implemented here with real data provider
    print(f"Note: US price data requires additional API provider configuration")
    print(f"{'='*60}\n")

    logger.info("us_fetch_complete", stocks_loaded=loaded_stocks)


async def main_async(
    market: str,
    days: int,
    sample: int | None,
) -> None:
    """Main async function."""
    try:
        await DataLoader()._db.create_tables()

        if market == "krx":
            await run_fetch_krx(days=days, sample=sample)
        elif market == "us":
            await run_fetch_us(days=days, sample=sample)
        elif market == "both":
            await run_fetch_krx(days=days, sample=sample)
            await run_fetch_us(days=days, sample=sample)

    except KeyboardInterrupt:
        print("\nOperation cancelled.")
        sys.exit(0)
    except Exception as e:
        logger.error("fetch_error", error=str(e))
        print(f"\nError: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        db = get_db_manager()
        await db.close()


def main() -> None:
    """Entry point."""
    parser = argparse.ArgumentParser(
        description="Fetch stock list and price data into database",
    )
    parser.add_argument(
        "--market",
        "-m",
        choices=["krx", "us", "both"],
        default="krx",
        help="Market to fetch (default: krx)",
    )
    parser.add_argument(
        "--days",
        "-d",
        type=int,
        default=100,
        help="Number of days of price history to fetch (default: 100)",
    )
    parser.add_argument(
        "--sample",
        "-s",
        type=int,
        default=None,
        help="Limit to first N stocks for testing (default: all)",
    )
    parser.add_argument(
        "--log-level",
        "-l",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Log level (default: INFO)",
    )

    args = parser.parse_args()

    configure_logging(level=args.log_level)

    print(f"\n{'='*60}")
    print(f"Turtle-CANSLIM Data Fetcher")
    print(f"{'='*60}")
    print(f"Market: {args.market.upper()}")
    print(f"Days:   {args.days}")
    if args.sample:
        print(f"Sample: {args.sample} stocks")
    print(f"{'='*60}\n")

    asyncio.run(
        main_async(
            market=args.market,
            days=args.days,
            sample=args.sample,
        )
    )


if __name__ == "__main__":
    main()
