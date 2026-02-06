from __future__ import annotations

import asyncio
import io
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Callable, Sequence

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import get_settings
from src.core.logger import get_logger
from src.data.dart_client import DARTClient
from src.data.models import DailyPrice, Fundamental, Stock
from src.data.repositories import (
    DailyPriceRepository,
    FundamentalRepository,
    StockRepository,
)

logger = get_logger(__name__)

DART_BASE_URL = "https://opendart.fss.or.kr/api"
DART_RATE_DELAY = 0.5

US_FALLBACK_TICKERS = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "BRK-B", "AVGO", "JPM",
    "LLY", "V", "UNH", "MA", "COST", "HD", "PG", "JNJ", "ABBV", "NFLX",
    "CRM", "AMD", "WMT", "BAC", "ORCL", "MRK", "PEP", "KO", "TMO", "ADBE",
    "CSCO", "ACN", "LIN", "MCD", "ABT", "TXN", "GE", "ISRG", "INTU", "QCOM",
    "AMGN", "CAT", "NOW", "PFE", "IBM", "GS", "BX", "AMAT", "HON", "BKNG",
]

SEC_EDGAR_TICKERS_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
SEC_USER_AGENT = "TurtleCANSLIM contact@example.com"
NASDAQ_SCREENER_URL = "https://api.nasdaq.com/api/screener/stocks"
US_MIN_MARKET_CAP = 300_000_000

KRX_RATE_DELAY = 0.2
YF_RATE_DELAY = 0.3

STALE_THRESHOLD_DAYS = 1

INDEX_SYMBOLS: dict[str, list[tuple[str, str]]] = {
    "krx": [("^KOSPI", "KOSPI"), ("^KOSDAQ", "KOSDAQ")],
    "us": [("^GSPC", "NYSE"), ("^IXIC", "NASDAQ")],
}

_MARKET_LISTS: dict[str, list[str]] = {
    "krx": ["KOSPI", "KOSDAQ", "krx"],
    "us": ["NYSE", "NASDAQ", "US", "us"],
}


class AutoDataFetcher:
    def __init__(self, session: AsyncSession):
        self._session = session
        self._stock_repo = StockRepository(session)
        self._price_repo = DailyPriceRepository(session)
        self._fundamental_repo = FundamentalRepository(session)
        self._dart_client: DARTClient | None = None
        self._corp_code_cache: dict[str, str] = {}

    def _get_dart_client(self) -> DARTClient | None:
        if self._dart_client is None:
            try:
                self._dart_client = DARTClient()
            except Exception:
                return None
        return self._dart_client

    def _market_values(self, market: str) -> list[str]:
        return _MARKET_LISTS.get(market.lower(), [market])

    async def has_data(self, market: str) -> bool:
        markets = self._market_values(market)

        stmt = (
            select(func.count())
            .select_from(Stock)
            .where(Stock.market.in_(markets), Stock.is_active == True)
        )
        result = await self._session.execute(stmt)
        if result.scalar_one() == 0:
            return False

        stmt_prices = (
            select(func.count())
            .select_from(DailyPrice)
            .join(Stock)
            .where(Stock.market.in_(markets))
        )
        result_prices = await self._session.execute(stmt_prices)
        return result_prices.scalar_one() > 0

    async def get_latest_price_date(self, market: str) -> datetime | None:
        markets = self._market_values(market)
        stmt = (
            select(func.max(DailyPrice.date))
            .join(Stock)
            .where(Stock.market.in_(markets))
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def is_data_stale(self, market: str) -> bool:
        latest = await self.get_latest_price_date(market)
        if latest is None:
            return True
        now = datetime.now()
        age = (now - latest).days
        # 주말 보정: 금요일 데이터가 최신이면 월요일까지는 stale 아님
        weekday = now.weekday()
        if weekday == 0:  # 월요일
            return age > 3
        if weekday == 6:  # 일요일
            return age > 2
        return age > STALE_THRESHOLD_DAYS

    async def fetch_and_store(
        self,
        market: str,
        progress_callback: Callable[[str], None] | None = None,
    ) -> int:
        market_lower = market.lower()

        if market_lower == "krx":
            return await self._fetch_krx(progress_callback)
        elif market_lower == "us":
            return await self._fetch_us(progress_callback)
        elif market_lower == "both":
            krx = await self._fetch_krx(progress_callback)
            us = await self._fetch_us(progress_callback)
            return krx + us
        else:
            logger.error("unsupported_market", market=market)
            return 0

    async def update_prices(
        self,
        market: str,
        progress_callback: Callable[[str], None] | None = None,
    ) -> int:
        market_lower = market.lower()

        if market_lower == "both":
            krx = await self._update_market_prices("krx", progress_callback)
            us = await self._update_market_prices("us", progress_callback)
            return krx + us

        return await self._update_market_prices(market_lower, progress_callback)

    async def ensure_data(
        self,
        market: str,
        progress_callback: Callable[[str], None] | None = None,
    ) -> bool:
        market_lower = market.lower()

        if market_lower == "both":
            return await self._ensure_single("krx", progress_callback) and \
                   await self._ensure_single("us", progress_callback)

        return await self._ensure_single(market_lower, progress_callback)

    async def _db_stock_count(self, market: str) -> int:
        markets = self._market_values(market)
        stmt = (
            select(func.count())
            .select_from(Stock)
            .where(Stock.market.in_(markets), Stock.is_active == True)  # noqa: E712
        )
        result = await self._session.execute(stmt)
        return result.scalar_one()

    async def _is_universe_stale(self, market: str) -> bool:
        db_count = await self._db_stock_count(market)
        if db_count == 0:
            return True

        market_lower = market.lower()
        if market_lower == "krx":
            try:
                from pykrx import stock as pykrx_stock
                loop = asyncio.get_event_loop()
                kospi = await loop.run_in_executor(
                    None, pykrx_stock.get_market_ticker_list, None, "KOSPI"
                )
                kosdaq = await loop.run_in_executor(
                    None, pykrx_stock.get_market_ticker_list, None, "KOSDAQ"
                )
                expected = len(kospi) + len(kosdaq)
            except Exception:
                return False
        elif market_lower == "us":
            try:
                ticker_list = await self._fetch_us_ticker_list(None)
                expected = len(ticker_list)
            except Exception:
                return False
        else:
            return False

        ratio = db_count / expected if expected > 0 else 1.0
        return ratio < 0.8

    async def _ensure_single(
        self,
        market: str,
        progress_callback: Callable[[str], None] | None,
    ) -> bool:
        has = await self.has_data(market)

        if not has:
            if progress_callback:
                progress_callback(f"데이터가 없습니다. 자동 수집을 시작합니다... ({market.upper()})")
            loaded = await self.fetch_and_store(market, progress_callback)
            if loaded == 0:
                return False
            if market.lower() == "krx":
                await self.fetch_krx_financials(progress_callback)
        else:
            universe_stale = await self._is_universe_stale(market)
            if universe_stale:
                db_count = await self._db_stock_count(market)
                if progress_callback:
                    progress_callback(
                        f"종목 유니버스 확장 필요 (현재 DB: {db_count}개). "
                        f"전체 종목 수집 시작... ({market.upper()})"
                    )
                loaded = await self.fetch_and_store(market, progress_callback)
                if loaded > 0 and market.lower() == "krx":
                    await self.fetch_krx_financials(progress_callback)

            stale = await self.is_data_stale(market)
            if stale:
                latest = await self.get_latest_price_date(market)
                age = (datetime.now() - latest).days if latest else 999
                if progress_callback:
                    progress_callback(f"데이터가 {age}일 전입니다. 최신 데이터로 업데이트 중... ({market.upper()})")
                await self.update_prices(market, progress_callback)

            if market.lower() in ("krx", "us"):
                fundamentals_stale = await self._is_fundamentals_stale(market)
                if fundamentals_stale:
                    if progress_callback:
                        progress_callback(f"재무제표 데이터가 오래되었습니다. 업데이트 중... ({market.upper()})")
                    if market.lower() == "krx":
                        await self.fetch_krx_financials(progress_callback)
                    else:
                        await self.update_us_financials(progress_callback)

        if market.lower() in ("krx", "us"):
            if await self._is_index_data_missing(market):
                await self.fetch_market_indices(market, progress_callback)
            if await self._is_metadata_missing(market):
                await self.update_stock_metadata(market, progress_callback)

        return True

    async def _is_index_data_missing(self, market: str) -> bool:
        now = datetime.now()
        weekday = now.weekday()
        if weekday == 0:
            max_age_days = 3
        elif weekday == 6:
            max_age_days = 2
        else:
            max_age_days = STALE_THRESHOLD_DAYS
        index_syms = [sym for sym, _ in INDEX_SYMBOLS.get(market.lower(), [])]
        if not index_syms:
            return False
        for sym in index_syms:
            stock = await self._stock_repo.get_by_symbol(sym)
            if not stock:
                return True
            latest_prices = await self._price_repo.get_latest(stock.id, limit=1)
            if not latest_prices:
                return True
            age = (now.date() - latest_prices[0].date.date()).days
            if age > max_age_days:
                return True
        return False

    async def _is_metadata_missing(self, market: str) -> bool:
        markets = self._market_values(market)
        unfilled_stmt = (
            select(func.count())
            .select_from(Stock)
            .where(
                Stock.market.in_(markets),
                Stock.is_active == True,  # noqa: E712
                Stock.shares_outstanding.is_(None),
            )
        )
        unfilled = (await self._session.execute(unfilled_stmt)).scalar_one()
        return unfilled > 0

    @staticmethod
    def _expected_available_quarter(now: datetime) -> tuple[int, int]:
        """Return (year, quarter) of the latest report expected to be filed.

        DART filing deadlines (approx):
          Q1 (Jan-Mar)  → available ~May 15
          Q2 (Apr-Jun)  → available ~Aug 14
          Q3 (Jul-Sep)  → available ~Nov 14
          Q4 (Oct-Dec)  → available ~Mar 31 next year (annual)
        """
        month = now.month
        year = now.year

        if month >= 11:
            return (year, 3)
        elif month >= 8:
            return (year, 2)
        elif month >= 5:
            return (year, 1)
        elif month >= 4:
            return (year - 1, 4)
        else:
            return (year - 1, 3)

    async def _is_fundamentals_stale(self, market: str) -> bool:
        markets = self._market_values(market)
        stocks_stmt = (
            select(Stock).where(
                Stock.market.in_(markets),
                Stock.is_active == True,
            )
        )
        result = await self._session.execute(stocks_stmt)
        stocks = result.scalars().all()
        if not stocks:
            return True

        stock_ids = [s.id for s in stocks]
        latest = await self._fundamental_repo.get_latest_period(stock_ids)
        if latest is None:
            return True

        db_year, db_quarter = latest
        if db_quarter is None:
            db_quarter = 4
        db_period = db_year * 10 + db_quarter

        market_lower = market.lower()
        if market_lower == "krx":
            api_period = await self._get_krx_latest_available_period(stocks)
        else:
            api_period = await self._get_us_latest_available_period()

        if api_period is None:
            expected_year, expected_quarter = self._expected_available_quarter(datetime.now())
            if expected_quarter is None:
                expected_quarter = 4
            api_period = expected_year * 10 + expected_quarter

        return db_period < api_period

    async def _get_krx_latest_available_period(
        self, stocks: Sequence[Stock]
    ) -> int | None:
        dart_client = self._get_dart_client()
        if not dart_client:
            return None

        if not self._corp_code_cache:
            dart_api_key = get_settings().dart_api_key
            if dart_api_key:
                self._corp_code_cache = await self._load_dart_corp_codes(dart_api_key)

        sample_stocks = list(stocks)[:5]
        max_period = 0

        for stock in sample_stocks:
            corp_code = self._corp_code_cache.get(stock.symbol)
            if not corp_code:
                continue

            try:
                period, _ = await dart_client.get_latest_available_period(corp_code)
                if period and period > max_period:
                    max_period = period
            except Exception:
                continue

        return max_period if max_period > 0 else None

    async def _get_us_latest_available_period(self) -> int | None:
        try:
            import yfinance as yf
        except ImportError:
            return None

        import pandas as pd

        sample_symbols = ["AAPL", "MSFT", "GOOGL"]
        loop = asyncio.get_event_loop()
        max_period = 0

        for symbol in sample_symbols:
            try:
                ticker = yf.Ticker(symbol)
                quarterly = await loop.run_in_executor(
                    None, lambda t=ticker: t.quarterly_financials
                )
                if quarterly is not None and not quarterly.empty:
                    latest_col = quarterly.columns[0]
                    if isinstance(latest_col, pd.Timestamp):
                        year = latest_col.year
                        month = latest_col.month
                    else:
                        dt = pd.to_datetime(latest_col)
                        year = dt.year
                        month = dt.month
                    if month <= 3:
                        quarter = 1
                    elif month <= 6:
                        quarter = 2
                    elif month <= 9:
                        quarter = 3
                    else:
                        quarter = 4
                    period = year * 10 + quarter
                    if period > max_period:
                        max_period = period
            except Exception:
                continue

        return max_period if max_period > 0 else None

    def _missing_quarters(
        self,
        db_year: int,
        db_quarter: int,
        target_year: int,
        target_quarter: int,
    ) -> list[tuple[int, int]]:
        missing: list[tuple[int, int]] = []
        y, q = db_year, db_quarter

        while True:
            q += 1
            if q > 4:
                q = 1
                y += 1
            if y * 10 + q > target_year * 10 + target_quarter:
                break
            missing.append((y, q))

        return missing

    # ── Incremental Update ────────────────────────────────────

    async def _update_market_prices(
        self,
        market: str,
        progress_callback: Callable[[str], None] | None,
    ) -> int:
        stocks = await self._stock_repo.get_all_active(market)
        if not stocks:
            return 0

        latest = await self.get_latest_price_date(market)
        if latest is None:
            return await self.fetch_and_store(market, progress_callback)

        from_date = latest + timedelta(days=1)
        today = datetime.now()

        if from_date.date() > today.date():
            if progress_callback:
                progress_callback(f"{market.upper()} 데이터가 최신입니다.")
            return 0

        total = len(stocks)
        if progress_callback:
            progress_callback(f"{market.upper()} {total}개 종목 가격 업데이트 중 ({from_date.strftime('%Y-%m-%d')} ~ {today.strftime('%Y-%m-%d')})...")

        market_lower = market.lower()
        if market_lower == "krx":
            return await self._incremental_krx(stocks, from_date, today, progress_callback)
        elif market_lower == "us":
            return await self._incremental_us(stocks, from_date, today, progress_callback)
        return 0

    async def _incremental_krx(
        self,
        stocks: list,
        from_date: datetime,
        to_date: datetime,
        progress_callback: Callable[[str], None] | None,
    ) -> int:
        try:
            from pykrx import stock as pykrx_stock
        except ImportError:
            return 0

        loop = asyncio.get_event_loop()
        fromdate_str = from_date.strftime("%Y%m%d")
        todate_str = to_date.strftime("%Y%m%d")
        total = len(stocks)
        updated = 0

        for i, stock in enumerate(stocks, 1):
            try:
                if progress_callback and i % 10 == 1:
                    progress_callback(f"[{i}/{total}] {stock.symbol} 업데이트 중...")

                df = await loop.run_in_executor(
                    None, pykrx_stock.get_market_ohlcv_by_date, fromdate_str, todate_str, stock.symbol
                )
                await asyncio.sleep(KRX_RATE_DELAY)

                if df is None or df.empty:
                    continue

                prices = self._df_to_krx_prices(df)
                if prices:
                    await self._price_repo.bulk_create(stock.id, prices)
                    await self._session.commit()
                    updated += 1

            except Exception as e:
                logger.warning("krx_update_error", symbol=stock.symbol, error=str(e))
                await self._session.rollback()
                continue

        if progress_callback:
            progress_callback(f"KRX 가격 업데이트 완료: {updated}/{total}개 종목")
        return updated

    async def _incremental_us(
        self,
        stocks: list,
        from_date: datetime,
        to_date: datetime,
        progress_callback: Callable[[str], None] | None,
    ) -> int:
        try:
            import yfinance as yf
        except ImportError:
            return 0

        loop = asyncio.get_event_loop()
        start_str = from_date.strftime("%Y-%m-%d")
        end_str = (to_date + timedelta(days=1)).strftime("%Y-%m-%d")
        total = len(stocks)
        updated = 0

        for i, stock in enumerate(stocks, 1):
            try:
                if progress_callback and i % 10 == 1:
                    progress_callback(f"[{i}/{total}] {stock.symbol} 업데이트 중...")

                ticker_obj = yf.Ticker(stock.symbol)
                hist = await loop.run_in_executor(
                    None, lambda t=ticker_obj, s=start_str, e=end_str: t.history(start=s, end=e)
                )
                await asyncio.sleep(YF_RATE_DELAY)

                if hist is None or hist.empty:
                    continue

                prices = self._df_to_us_prices(hist)
                if prices:
                    await self._price_repo.bulk_create(stock.id, prices)
                    await self._session.commit()
                    updated += 1

            except Exception as e:
                logger.warning("us_update_error", symbol=stock.symbol, error=str(e))
                await self._session.rollback()
                continue

        if progress_callback:
            progress_callback(f"US 가격 업데이트 완료: {updated}/{total}개 종목")
        return updated

    # ── Full Fetch (initial load) ─────────────────────────────

    async def _fetch_krx(
        self,
        progress_callback: Callable[[str], None] | None,
    ) -> int:
        if progress_callback:
            progress_callback("KRX 전체 종목 목록 수집 중...")

        loop = asyncio.get_event_loop()

        try:
            from pykrx import stock as pykrx_stock
        except ImportError:
            logger.error("pykrx_not_installed")
            if progress_callback:
                progress_callback("오류: pykrx 패키지가 설치되지 않았습니다. pip install pykrx")
            return 0

        kospi_tickers = await loop.run_in_executor(
            None, pykrx_stock.get_market_ticker_list, None, "KOSPI"
        )
        kosdaq_tickers = await loop.run_in_executor(
            None, pykrx_stock.get_market_ticker_list, None, "KOSDAQ"
        )

        ticker_market_pairs: list[tuple[str, str]] = []
        for t in kospi_tickers:
            ticker_market_pairs.append((t, "KOSPI"))
        for t in kosdaq_tickers:
            ticker_market_pairs.append((t, "KOSDAQ"))

        total = len(ticker_market_pairs)

        if progress_callback:
            progress_callback(f"총 {total}개 종목 수집 대상")

        today = datetime.now()
        fromdate = (today - timedelta(days=365)).strftime("%Y%m%d")
        todate = today.strftime("%Y%m%d")

        loaded = 0
        for i, (ticker, mkt) in enumerate(ticker_market_pairs, 1):
            try:
                name = await loop.run_in_executor(
                    None, pykrx_stock.get_market_ticker_name, ticker
                )
                await asyncio.sleep(KRX_RATE_DELAY)

                if progress_callback:
                    progress_callback(f"[{i}/{total}] {ticker} {name} 가격 데이터 수집 중...")

                df = await loop.run_in_executor(
                    None, pykrx_stock.get_market_ohlcv_by_date, fromdate, todate, ticker
                )
                await asyncio.sleep(KRX_RATE_DELAY)

                if df is None or df.empty:
                    logger.warning("krx_empty_data", ticker=ticker)
                    continue

                stock = await self._stock_repo.get_or_create(
                    symbol=ticker, name=name or ticker, market=mkt
                )

                prices = self._df_to_krx_prices(df)
                if prices:
                    await self._price_repo.bulk_create(stock.id, prices)

                await self._session.commit()
                loaded += 1

            except Exception as e:
                logger.error("krx_stock_error", ticker=ticker, error=str(e))
                await self._session.rollback()
                continue

        if progress_callback:
            progress_callback(f"KRX 데이터 수집 완료: {loaded}/{total}개 종목")

        return loaded

    async def _fetch_us_ticker_list(
        self,
        progress_callback: Callable[[str], None] | None,
    ) -> list[tuple[str, str, str]]:
        if progress_callback:
            progress_callback("SEC EDGAR에서 NYSE/NASDAQ 전체 종목 목록 수집 중...")

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                edgar_resp = await client.get(
                    SEC_EDGAR_TICKERS_URL,
                    headers={"User-Agent": SEC_USER_AGENT},
                )
                edgar_resp.raise_for_status()
                edgar_data = edgar_resp.json()

            fields = edgar_data.get("fields", [])
            rows = edgar_data.get("data", [])

            ticker_idx = fields.index("ticker") if "ticker" in fields else 2
            name_idx = fields.index("name") if "name" in fields else 1
            exchange_idx = fields.index("exchange") if "exchange" in fields else 3

            edgar_map: dict[str, tuple[str, str]] = {}
            for row in rows:
                exc = row[exchange_idx]
                if exc not in ("NYSE", "Nasdaq"):
                    continue
                symbol = str(row[ticker_idx]).upper()
                name = str(row[name_idx])
                market_label = "NASDAQ" if exc == "Nasdaq" else "NYSE"
                edgar_map[symbol] = (name, market_label)

            if progress_callback:
                progress_callback(f"SEC EDGAR: NYSE/NASDAQ {len(edgar_map)}개 종목 발견. 시가총액 필터링 중...")

            nasdaq_resp = await self._fetch_nasdaq_screener()
            cap_map: dict[str, float] = {}
            for item in nasdaq_resp:
                sym = item.get("symbol", "").upper()
                cap_str = item.get("marketCap", "")
                if not cap_str or cap_str in ("", "NA", "N/A"):
                    continue
                try:
                    cap_map[sym] = float(str(cap_str).replace(",", "").replace("$", ""))
                except ValueError:
                    continue

            result: list[tuple[str, str, str]] = []
            for symbol, (name, market_label) in edgar_map.items():
                cap = cap_map.get(symbol)
                if cap is not None and cap >= US_MIN_MARKET_CAP:
                    result.append((symbol, name, market_label))

            no_cap_in_edgar = [s for s in edgar_map if s not in cap_map]
            if progress_callback:
                progress_callback(
                    f"시가총액 $300M+ 필터 완료: {len(result)}개 종목 "
                    f"(시가총액 정보 없음: {len(no_cap_in_edgar)}개 제외)"
                )

            if len(result) < 100:
                logger.warning("us_ticker_list_too_small", count=len(result))
                if progress_callback:
                    progress_callback(f"동적 리스트가 너무 적음({len(result)}개). 폴백 리스트 사용.")
                return [
                    (sym, sym, "NYSE") for sym in US_FALLBACK_TICKERS
                ]

            return result

        except Exception as e:
            logger.error("us_ticker_list_fetch_failed", error=str(e))
            if progress_callback:
                progress_callback(f"종목 리스트 수집 실패: {e}. 폴백 리스트({len(US_FALLBACK_TICKERS)}개) 사용.")
            return [(sym, sym, "NYSE") for sym in US_FALLBACK_TICKERS]

    @staticmethod
    async def _fetch_nasdaq_screener() -> list[dict]:
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.get(
                    NASDAQ_SCREENER_URL,
                    params={"tableType": "traded", "limit": "10000", "offset": "0"},
                    headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
                )
                resp.raise_for_status()
                data = resp.json()
                return data.get("data", {}).get("table", {}).get("rows", [])
        except Exception as e:
            logger.error("nasdaq_screener_failed", error=str(e))
            return []

    async def _fetch_us(
        self,
        progress_callback: Callable[[str], None] | None,
    ) -> int:
        try:
            import yfinance as yf
        except ImportError:
            logger.error("yfinance_not_installed")
            if progress_callback:
                progress_callback("오류: yfinance 패키지가 설치되지 않았습니다. pip install yfinance")
            return 0

        ticker_list = await self._fetch_us_ticker_list(progress_callback)
        total = len(ticker_list)

        if progress_callback:
            progress_callback(f"US {total}개 종목 데이터 수집 시작 (배치 다운로드)...")

        loop = asyncio.get_event_loop()

        ticker_map: dict[str, tuple[str, str]] = {}
        for symbol, name_hint, market_hint in ticker_list:
            ticker_map[symbol] = (name_hint, market_hint)

        symbols = list(ticker_map.keys())
        batch_size = 50
        loaded = 0

        for batch_start in range(0, len(symbols), batch_size):
            batch_symbols = symbols[batch_start:batch_start + batch_size]
            batch_num = batch_start // batch_size + 1
            total_batches = (len(symbols) + batch_size - 1) // batch_size

            if progress_callback:
                progress_callback(
                    f"[배치 {batch_num}/{total_batches}] "
                    f"{batch_symbols[0]}~{batch_symbols[-1]} "
                    f"가격 다운로드 중... (완료: {loaded}/{total})"
                )

            try:
                batch_data = await loop.run_in_executor(
                    None,
                    lambda syms=batch_symbols: yf.download(
                        syms, period="1y", group_by="ticker",
                        progress=False, threads=True,
                    ),
                )
            except Exception as e:
                logger.error("us_batch_download_error", batch=batch_num, error=str(e))
                continue

            for symbol in batch_symbols:
                name_hint, market_hint = ticker_map[symbol]
                try:
                    if len(batch_symbols) == 1:
                        sym_data = batch_data
                    else:
                        if symbol not in batch_data.columns.get_level_values(0):
                            continue
                        sym_data = batch_data[symbol]

                    if sym_data is None or sym_data.empty:
                        continue

                    sym_data = sym_data.dropna(subset=["Close"])
                    if sym_data.empty:
                        continue

                    stock = await self._stock_repo.get_or_create(
                        symbol=symbol,
                        name=name_hint,
                        market=market_hint,
                    )

                    prices = self._df_to_us_prices(sym_data)
                    if prices:
                        await self._price_repo.bulk_create(stock.id, prices)

                    await self._session.commit()
                    loaded += 1

                except Exception as e:
                    logger.error("us_stock_error", symbol=symbol, error=str(e))
                    await self._session.rollback()
                    continue

            await asyncio.sleep(0.5)

        if progress_callback:
            progress_callback(f"US 가격 데이터 수집 완료: {loaded}/{total}개 종목")

        if progress_callback:
            progress_callback(f"US 재무제표 수집 중 ({total}개 종목)...")
        fundamentals_loaded = await self._batch_us_fundamentals(
            symbols, loop, yf, progress_callback,
        )
        if progress_callback:
            progress_callback(f"US 재무제표 수집 완료: {fundamentals_loaded}/{total}개 종목")

        return loaded

    async def _batch_us_fundamentals(
        self,
        symbols: list[str],
        loop: asyncio.AbstractEventLoop,
        yf_module: object,
        progress_callback: Callable[[str], None] | None,
    ) -> int:
        loaded = 0
        total = len(symbols)
        for i, symbol in enumerate(symbols, 1):
            try:
                if progress_callback and (i % 50 == 1 or i == total):
                    progress_callback(f"  재무제표 [{i}/{total}] {symbol}... (완료: {loaded})")

                ticker_obj = yf_module.Ticker(symbol)  # type: ignore[union-attr]
                stock = await self._stock_repo.get_by_symbol(symbol)
                if stock is None:
                    continue

                await self._store_us_fundamentals(stock.id, ticker_obj, loop)
                await self._session.commit()
                loaded += 1

            except Exception as e:
                logger.error("us_fundamental_error", symbol=symbol, error=str(e))
                await self._session.rollback()
                continue

        return loaded

    # ── DART Financial Statements (KRX) ──────────────────────

    _DART_REPORT_CODES: dict[int, str] = {
        1: "11013",
        2: "11012",
        3: "11014",
        4: "11011",
    }

    async def fetch_krx_financials(
        self,
        progress_callback: Callable[[str], None] | None = None,
        full_history: bool = False,
    ) -> int:
        updated = 0

        try:
            pykrx_count = await self._fetch_krx_fundamentals_pykrx(progress_callback)
            updated += pykrx_count
        except Exception as e:
            logger.warning("pykrx_fundamentals_error", error=str(e))
            if progress_callback:
                progress_callback(f"[경고] pykrx 재무데이터 수집 실패: {e}")

        dart_api_key = get_settings().dart_api_key
        if dart_api_key:
            try:
                batch_count = await self._fetch_krx_fundamentals_dart_batch(
                    dart_api_key, progress_callback
                )
                if batch_count > 0:
                    updated += batch_count
                else:
                    updated += await self._fetch_krx_financials_individual(
                        dart_api_key, progress_callback, full_history
                    )
            except Exception as e:
                logger.warning("dart_batch_fundamentals_error", error=str(e))
                if progress_callback:
                    progress_callback(f"[경고] DART 배치 수집 실패, 개별 수집으로 전환...")
                try:
                    updated += await self._fetch_krx_financials_individual(
                        dart_api_key, progress_callback, full_history
                    )
                except Exception as e2:
                    logger.warning("dart_individual_fallback_error", error=str(e2))

        return updated

    async def _fetch_krx_fundamentals_pykrx(
        self,
        progress_callback: Callable[[str], None] | None,
    ) -> int:
        try:
            from pykrx import stock as pykrx_stock
        except ImportError:
            logger.warning("pykrx_not_installed_for_fundamentals")
            if progress_callback:
                progress_callback("[경고] pykrx 패키지가 없습니다. 연간 재무데이터 건너뜀.")
            return 0

        loop = asyncio.get_event_loop()
        now = datetime.now()
        current_year = now.year
        years = [current_year - i for i in range(4)]

        stocks = await self._stock_repo.get_all_active("krx")
        if not stocks:
            return 0

        symbol_to_stock = {s.symbol: s for s in stocks}

        if progress_callback:
            progress_callback(f"pykrx 연간 재무데이터 수집 중 ({len(years)}개년)...")

        total_updated = 0

        for year in years:
            df = None
            for day_offset in [30, 29, 28, 27]:
                date_str = f"{year}12{day_offset}"
                try:
                    df = await loop.run_in_executor(
                        None,
                        lambda d=date_str: pykrx_stock.get_market_fundamental(d, market="ALL"),
                    )
                    if df is not None and not df.empty:
                        break
                except Exception:
                    continue

            if df is None or df.empty:
                logger.warning("pykrx_fundamental_empty", year=year)
                if progress_callback:
                    progress_callback(f"[경고] {year}년 pykrx 재무데이터 없음")
                continue

            year_count = 0
            for ticker in df.index:
                try:
                    stock = symbol_to_stock.get(ticker)
                    if not stock:
                        continue

                    row = df.loc[ticker]
                    eps_val = row.get("EPS")
                    bps_val = row.get("BPS")

                    if eps_val is None and bps_val is None:
                        continue

                    eps = Decimal(str(int(eps_val))) if eps_val and eps_val != 0 else None
                    bps = Decimal(str(int(bps_val))) if bps_val and bps_val != 0 else None

                    roe = None
                    if eps is not None and bps is not None and bps != 0:
                        roe = eps / bps

                    await self._fundamental_repo.upsert(
                        stock_id=stock.id,
                        fiscal_year=year,
                        fiscal_quarter=None,
                        revenue=None,
                        operating_income=None,
                        net_income=None,
                        eps=eps,
                        total_assets=None,
                        total_equity=None,
                        roe=roe,
                    )
                    year_count += 1

                except Exception as e:
                    logger.warning("pykrx_fundamental_ticker_error", ticker=ticker, error=str(e))
                    continue

            await self._session.commit()
            total_updated += year_count

            if progress_callback:
                progress_callback(f"pykrx {year}년 재무데이터: {year_count}개 종목 업데이트")

        if progress_callback:
            progress_callback(f"pykrx 연간 재무데이터 수집 완료: 총 {total_updated}건")

        return total_updated

    async def _fetch_krx_fundamentals_dart_batch(
        self,
        dart_api_key: str,
        progress_callback: Callable[[str], None] | None,
    ) -> int:
        if progress_callback:
            progress_callback("DART 배치 재무제표 수집 시작...")

        corp_map = await self._load_dart_corp_codes(dart_api_key)
        if not corp_map:
            if progress_callback:
                progress_callback("[경고] DART corp_code 매핑을 로드할 수 없습니다.")
            return 0

        stocks = await self._stock_repo.get_all_active("krx")
        if not stocks:
            return 0

        symbol_to_stock = {s.symbol: s for s in stocks}

        stock_corp_pairs: list[tuple[str, str]] = []
        for stock in stocks:
            corp_code = corp_map.get(stock.symbol)
            if corp_code:
                stock_corp_pairs.append((stock.symbol, corp_code))

        if not stock_corp_pairs:
            return 0

        expected_year, expected_quarter = self._expected_available_quarter(datetime.now())

        quarters_to_fetch: list[tuple[int, int]] = [
            (expected_year, expected_quarter),
            (expected_year - 1, expected_quarter),
        ]

        if progress_callback:
            q_label = ", ".join(f"{y}Q{q}" for y, q in quarters_to_fetch)
            progress_callback(
                f"DART 배치 수집 대상: {q_label} ({len(stock_corp_pairs)}개 종목)"
            )

        batch_size = 100
        total_updated = 0

        account_mapping = {
            "매출액": "revenue",
            "영업이익": "operating_income",
            "당기순이익": "net_income",
            "당기순이익(손실)": "net_income",
            "자산총계": "total_assets",
            "자본총계": "total_equity",
        }

        for year, quarter in quarters_to_fetch:
            reprt_code = self._DART_REPORT_CODES.get(quarter, "11011")
            fiscal_quarter: int | None = quarter if quarter < 4 else None

            corp_codes_list = [cc for _, cc in stock_corp_pairs]

            for batch_start in range(0, len(corp_codes_list), batch_size):
                batch = corp_codes_list[batch_start:batch_start + batch_size]
                corp_code_param = ",".join(batch)

                try:
                    async with httpx.AsyncClient(timeout=30.0) as client:
                        resp = await client.get(
                            f"{DART_BASE_URL}/fnlttMultiAcnt.json",
                            params={
                                "crtfc_key": dart_api_key,
                                "corp_code": corp_code_param,
                                "bsns_year": str(year),
                                "reprt_code": reprt_code,
                            },
                        )
                        if resp.status_code != 200:
                            logger.warning(
                                "dart_batch_http_error",
                                status=resp.status_code,
                                batch_start=batch_start,
                            )
                            await asyncio.sleep(DART_RATE_DELAY)
                            continue

                        data = resp.json()

                    status = data.get("status")
                    if status and status != "000":
                        await asyncio.sleep(DART_RATE_DELAY)
                        continue

                    items = data.get("list", [])
                    if not items:
                        await asyncio.sleep(DART_RATE_DELAY)
                        continue

                    grouped: dict[str, dict[str, Decimal | None]] = {}
                    for item in items:
                        stock_code = item.get("stock_code", "").strip()
                        if not stock_code:
                            continue

                        if stock_code not in grouped:
                            grouped[stock_code] = {
                                "revenue": None,
                                "operating_income": None,
                                "net_income": None,
                                "total_assets": None,
                                "total_equity": None,
                            }

                        account_nm = item.get("account_nm", "")
                        matched_key = None
                        for kr_name, eng_key in account_mapping.items():
                            if kr_name in account_nm:
                                matched_key = eng_key
                                break

                        if matched_key and grouped[stock_code].get(matched_key) is None:
                            amount_str = item.get("thstrm_amount", "").replace(",", "")
                            if amount_str and amount_str != "-":
                                try:
                                    grouped[stock_code][matched_key] = Decimal(amount_str)
                                except (ValueError, ArithmeticError):
                                    pass

                    for stock_code, financials in grouped.items():
                        stock = symbol_to_stock.get(stock_code)
                        if not stock:
                            continue

                        roe = None
                        if financials["net_income"] and financials["total_equity"]:
                            equity = financials["total_equity"]
                            if equity != 0:
                                roe = financials["net_income"] / equity

                        await self._fundamental_repo.upsert(
                            stock_id=stock.id,
                            fiscal_year=year,
                            fiscal_quarter=fiscal_quarter,
                            revenue=financials["revenue"],
                            operating_income=financials["operating_income"],
                            net_income=financials["net_income"],
                            eps=None,
                            total_assets=financials["total_assets"],
                            total_equity=financials["total_equity"],
                            roe=roe,
                        )

                        q = fiscal_quarter if fiscal_quarter else 4
                        period = year * 10 + q
                        await self._stock_repo.update_fetched_period(stock.id, period)

                        total_updated += 1

                    await self._session.commit()

                except Exception as e:
                    logger.warning(
                        "dart_batch_error",
                        batch_start=batch_start,
                        error=str(e),
                    )

                await asyncio.sleep(DART_RATE_DELAY)

            if progress_callback:
                progress_callback(
                    f"DART 배치 {year}Q{quarter} 완료: {total_updated}건"
                )

        if progress_callback:
            progress_callback(f"DART 배치 재무제표 수집 완료: 총 {total_updated}건")

        return total_updated

    async def _fetch_krx_financials_individual(
        self,
        dart_api_key: str,
        progress_callback: Callable[[str], None] | None = None,
        full_history: bool = False,
    ) -> int:
        stocks = await self._stock_repo.get_all_active("krx")
        if not stocks:
            return 0

        if progress_callback:
            progress_callback("DART corp_code 매핑 다운로드 중...")

        corp_map = await self._load_dart_corp_codes(dart_api_key)
        if not corp_map:
            if progress_callback:
                progress_callback("[경고] DART corp_code 매핑을 로드할 수 없습니다.")
            return 0

        stock_ids = [s.id for s in stocks]
        db_latest = await self._fundamental_repo.get_latest_period(stock_ids)
        expected_year, expected_quarter = self._expected_available_quarter(datetime.now())

        if full_history or db_latest is None:
            quarters_to_fetch = self._initial_quarters(expected_year, expected_quarter)
        else:
            db_year, db_q = db_latest
            if db_q is None:
                db_q = 4
            quarters_to_fetch = self._missing_quarters(
                db_year, db_q, expected_year, expected_quarter
            )

        if not quarters_to_fetch:
            if progress_callback:
                progress_callback("KRX 재무제표가 최신 상태입니다.")
            return 0

        total = len(stocks)
        fetched = 0
        q_label = ", ".join(f"{y}Q{q}" for y, q in quarters_to_fetch)

        if progress_callback:
            progress_callback(f"DART 재무제표 수집 대상: {q_label} ({total}개 종목)")

        for i, stock in enumerate(stocks, 1):
            try:
                corp_code = corp_map.get(stock.symbol)
                if not corp_code:
                    continue

                if progress_callback and i % 5 == 1:
                    progress_callback(f"[{i}/{total}] {stock.symbol} {stock.name} 재무제표 수집 중...")

                for year, quarter in quarters_to_fetch:
                    await self._fetch_dart_report(
                        dart_api_key, corp_code, stock.id, year, quarter
                    )
                    await asyncio.sleep(DART_RATE_DELAY)

                fetched += 1

            except Exception as e:
                logger.warning("dart_fetch_error", symbol=stock.symbol, error=str(e))
                continue

        if progress_callback:
            progress_callback(f"DART 재무제표 수집 완료: {fetched}/{total}개 종목 ({q_label})")
        return fetched

    @staticmethod
    def _initial_quarters(
        target_year: int,
        target_quarter: int,
        history_years: int = 3,
    ) -> list[tuple[int, int]]:
        quarters: list[tuple[int, int]] = []
        start_year = target_year - history_years
        for y in range(start_year, target_year + 1):
            max_q = target_quarter if y == target_year else 4
            for q in range(1, max_q + 1):
                quarters.append((y, q))
        return quarters

    @staticmethod
    async def _load_dart_corp_codes(api_key: str) -> dict[str, str]:
        url = f"{DART_BASE_URL}/corpCode.xml"
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(url, params={"crtfc_key": api_key})
            if resp.status_code != 200:
                logger.error("dart_corp_code_download_failed", status=resp.status_code)
                return {}

        mapping: dict[str, str] = {}
        try:
            zf = zipfile.ZipFile(io.BytesIO(resp.content))
            xml_name = zf.namelist()[0]
            xml_bytes = zf.read(xml_name)
            root = ET.fromstring(xml_bytes)

            for corp in root.iter("list"):
                stock_code_el = corp.find("stock_code")
                corp_code_el = corp.find("corp_code")
                if (
                    stock_code_el is not None
                    and corp_code_el is not None
                    and stock_code_el.text
                    and stock_code_el.text.strip()
                ):
                    stock_code = stock_code_el.text.strip()
                    corp_code_text = corp_code_el.text or ""
                    if stock_code and corp_code_text:
                        mapping[stock_code] = corp_code_text.strip()
        except Exception as e:
            logger.error("dart_corp_code_parse_error", error=str(e))

        return mapping

    async def _fetch_dart_report(
        self,
        api_key: str,
        corp_code: str,
        stock_id: int,
        year: int,
        quarter: int,
    ) -> None:
        reprt_code = self._DART_REPORT_CODES.get(quarter, "11011")
        fiscal_quarter: int | None = quarter if quarter < 4 else None

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{DART_BASE_URL}/fnlttSinglAcntAll.json",
                params={
                    "crtfc_key": api_key,
                    "corp_code": corp_code,
                    "bsns_year": str(year),
                    "reprt_code": reprt_code,
                    "fs_div": "CFS",
                },
            )
            if resp.status_code != 200:
                return
            data = resp.json()

        status = data.get("status")
        if status and status != "000":
            return

        items = data.get("list", [])
        if not items:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(
                    f"{DART_BASE_URL}/fnlttSinglAcntAll.json",
                    params={
                        "crtfc_key": api_key,
                        "corp_code": corp_code,
                        "bsns_year": str(year),
                        "reprt_code": reprt_code,
                        "fs_div": "OFS",
                    },
                )
                if resp.status_code != 200:
                    return
                data = resp.json()
            items = data.get("list", [])

        if not items:
            return

        financials = self._parse_dart_items(items)

        roe = None
        if financials["net_income"] and financials["total_equity"]:
            equity = financials["total_equity"]
            if equity != 0:
                roe = financials["net_income"] / equity

        await self._fundamental_repo.upsert(
            stock_id=stock_id,
            fiscal_year=year,
            fiscal_quarter=fiscal_quarter,
            revenue=financials["revenue"],
            operating_income=financials["operating_income"],
            net_income=financials["net_income"],
            eps=financials["eps"],
            total_assets=financials["total_assets"],
            total_equity=financials["total_equity"],
            roe=roe,
        )

        q = fiscal_quarter if fiscal_quarter else 4
        period = year * 10 + q
        await self._stock_repo.update_fetched_period(stock_id, period)

        await self._session.commit()

    @staticmethod
    def _parse_dart_items(items: list[dict]) -> dict[str, Decimal | None]:
        financials: dict[str, Decimal | None] = {
            "revenue": None,
            "operating_income": None,
            "net_income": None,
            "eps": None,
            "total_assets": None,
            "total_equity": None,
        }

        account_mapping = {
            "ifrs-full_Revenue": "revenue",
            "ifrs-full_OperatingIncome": "operating_income",
            "ifrs-full_ProfitLoss": "net_income",
            "ifrs-full_BasicEarningsLossPerShare": "eps",
            "ifrs-full_Assets": "total_assets",
            "ifrs-full_Equity": "total_equity",
            "dart_OperatingIncomeLoss": "operating_income",
            "ifrs_Revenue": "revenue",
            "ifrs_ProfitLoss": "net_income",
        }

        for item in items:
            account_id = item.get("account_id", "")
            account_nm = item.get("account_nm", "")

            key = account_mapping.get(account_id)
            if not key:
                if "매출" in account_nm and "총" not in account_nm:
                    key = "revenue"
                elif "영업이익" in account_nm or "영업손익" in account_nm:
                    key = "operating_income"
                elif "당기순이익" in account_nm or "당기순손익" in account_nm:
                    key = "net_income"
                elif "기본주당" in account_nm and "이익" in account_nm:
                    key = "eps"
                elif "자산총계" in account_nm:
                    key = "total_assets"
                elif "자본총계" in account_nm:
                    key = "total_equity"

            if key and financials.get(key) is None:
                amount_str = item.get("thstrm_amount", "").replace(",", "")
                if amount_str and amount_str != "-":
                    try:
                        financials[key] = Decimal(amount_str)
                    except (ValueError, ArithmeticError):
                        pass

        return financials

    # ── US Financial Statements (yfinance) ───────────────────

    async def update_us_financials(
        self,
        progress_callback: Callable[[str], None] | None = None,
    ) -> int:
        try:
            import yfinance as yf
        except ImportError:
            if progress_callback:
                progress_callback("[경고] yfinance 패키지가 없습니다. US 재무제표 건너뜀.")
            return 0

        stocks = await self._stock_repo.get_all_active("us")
        if not stocks:
            return 0

        loop = asyncio.get_event_loop()
        total = len(stocks)
        fetched = 0

        if progress_callback:
            progress_callback(f"US {total}개 종목 재무제표 업데이트 중...")

        for i, stock in enumerate(stocks, 1):
            try:
                if progress_callback and i % 5 == 1:
                    progress_callback(f"[{i}/{total}] {stock.symbol} 재무제표 수집 중...")

                ticker_obj = yf.Ticker(stock.symbol)
                await self._store_us_fundamentals(stock.id, ticker_obj, loop)
                await self._session.commit()
                fetched += 1

            except Exception as e:
                logger.warning("us_financial_update_error", symbol=stock.symbol, error=str(e))
                await self._session.rollback()
                continue

        if progress_callback:
            progress_callback(f"US 재무제표 업데이트 완료: {fetched}/{total}개 종목")
        return fetched

    # ── DataFrame → price list converters ─────────────────────

    @staticmethod
    def _df_to_krx_prices(df) -> list[dict]:
        prices: list[dict] = []
        for date_idx, row in df.iterrows():
            dt = date_idx.to_pydatetime() if hasattr(date_idx, "to_pydatetime") else date_idx
            prices.append({
                "date": dt,
                "open": Decimal(str(row["시가"])),
                "high": Decimal(str(row["고가"])),
                "low": Decimal(str(row["저가"])),
                "close": Decimal(str(row["종가"])),
                "volume": int(row["거래량"]),
            })
        return prices

    @staticmethod
    def _df_to_us_prices(hist) -> list[dict]:
        prices: list[dict] = []
        for date_idx, row in hist.iterrows():
            dt = date_idx.to_pydatetime() if hasattr(date_idx, "to_pydatetime") else date_idx
            if hasattr(dt, "tzinfo") and dt.tzinfo is not None:
                dt = dt.replace(tzinfo=None)
            prices.append({
                "date": dt,
                "open": Decimal(str(round(row["Open"], 4))),
                "high": Decimal(str(round(row["High"], 4))),
                "low": Decimal(str(round(row["Low"], 4))),
                "close": Decimal(str(round(row["Close"], 4))),
                "volume": int(row["Volume"]),
            })
        return prices

    async def _store_us_fundamentals(
        self,
        stock_id: int,
        ticker_obj: object,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        try:
            financials = await loop.run_in_executor(
                None, lambda t=ticker_obj: t.financials
            )
            await asyncio.sleep(YF_RATE_DELAY)

            if financials is not None and not financials.empty:
                balance = await loop.run_in_executor(
                    None, lambda t=ticker_obj: t.balance_sheet
                )
                await asyncio.sleep(YF_RATE_DELAY)

                await self._upsert_yf_financials(
                    stock_id, financials, balance, fiscal_quarter=None
                )

            q_financials = await loop.run_in_executor(
                None, lambda t=ticker_obj: t.quarterly_financials
            )
            await asyncio.sleep(YF_RATE_DELAY)

            if q_financials is not None and not q_financials.empty:
                q_balance = await loop.run_in_executor(
                    None, lambda t=ticker_obj: t.quarterly_balance_sheet
                )
                await asyncio.sleep(YF_RATE_DELAY)

                for col in q_financials.columns:
                    try:
                        dt = col.to_pydatetime() if hasattr(col, "to_pydatetime") else col
                        fiscal_year = dt.year if hasattr(dt, "year") else int(str(col)[:4])
                        month = dt.month if hasattr(dt, "month") else 12
                        fiscal_quarter = (month - 1) // 3 + 1

                        revenue = self._safe_decimal(q_financials, "Total Revenue", col)
                        operating_income = self._safe_decimal(q_financials, "Operating Income", col)
                        net_income = self._safe_decimal(q_financials, "Net Income", col)
                        eps = self._safe_decimal(q_financials, "Basic EPS", col)

                        total_assets = None
                        total_equity = None
                        if q_balance is not None and not q_balance.empty and col in q_balance.columns:
                            total_assets = self._safe_decimal(q_balance, "Total Assets", col)
                            total_equity = self._safe_decimal(q_balance, "Stockholders Equity", col)
                            if total_equity is None:
                                total_equity = self._safe_decimal(q_balance, "Total Stockholder Equity", col)

                        roe = None
                        if net_income and total_equity and total_equity != 0:
                            roe = net_income / total_equity

                        await self._fundamental_repo.upsert(
                            stock_id=stock_id,
                            fiscal_year=fiscal_year,
                            fiscal_quarter=fiscal_quarter,
                            revenue=revenue,
                            operating_income=operating_income,
                            net_income=net_income,
                            eps=eps,
                            total_assets=total_assets,
                            total_equity=total_equity,
                            roe=roe,
                        )

                        period = fiscal_year * 10 + fiscal_quarter
                        await self._stock_repo.update_fetched_period(stock_id, period)

                    except Exception as e:
                        logger.warning("us_quarterly_period_error", stock_id=stock_id, error=str(e))
                        continue

        except Exception as e:
            logger.warning("us_fundamentals_error", stock_id=stock_id, error=str(e))

    async def _upsert_yf_financials(
        self,
        stock_id: int,
        financials: object,
        balance: object,
        fiscal_quarter: int | None,
    ) -> None:
        for col in financials.columns:
            try:
                fiscal_year = col.year if hasattr(col, "year") else int(str(col)[:4])

                revenue = self._safe_decimal(financials, "Total Revenue", col)
                operating_income = self._safe_decimal(financials, "Operating Income", col)
                net_income = self._safe_decimal(financials, "Net Income", col)
                eps = self._safe_decimal(financials, "Basic EPS", col)

                total_assets = None
                total_equity = None
                if balance is not None and not balance.empty and col in balance.columns:
                    total_assets = self._safe_decimal(balance, "Total Assets", col)
                    total_equity = self._safe_decimal(balance, "Stockholders Equity", col)
                    if total_equity is None:
                        total_equity = self._safe_decimal(balance, "Total Stockholder Equity", col)

                roe = None
                if net_income and total_equity and total_equity != 0:
                    roe = net_income / total_equity

                await self._fundamental_repo.upsert(
                    stock_id=stock_id,
                    fiscal_year=fiscal_year,
                    fiscal_quarter=fiscal_quarter,
                    revenue=revenue,
                    operating_income=operating_income,
                    net_income=net_income,
                    eps=eps,
                    total_assets=total_assets,
                    total_equity=total_equity,
                    roe=roe,
                )

                q = fiscal_quarter if fiscal_quarter else 4
                period = fiscal_year * 10 + q
                await self._stock_repo.update_fetched_period(stock_id, period)

            except Exception as e:
                logger.warning("us_fundamental_period_error", stock_id=stock_id, error=str(e))
                continue

    @staticmethod
    def _safe_decimal(df: object, label: str, col: object) -> Decimal | None:
        try:
            if label in df.index:
                val = df.loc[label, col]
                if val is not None and str(val) not in ("nan", "NaN", "None", ""):
                    return Decimal(str(round(float(val), 4)))
        except (ValueError, TypeError, KeyError):
            pass
        return None

    # ── Market Index Collection ───────────────────────────────

    async def fetch_market_indices(
        self,
        market: str,
        progress_callback: Callable[[str], None] | None = None,
    ) -> int:
        market_lower = market.lower()
        if market_lower == "both":
            krx = await self._fetch_indices_krx(progress_callback)
            us = await self._fetch_indices_us(progress_callback)
            return krx + us
        elif market_lower == "krx":
            return await self._fetch_indices_krx(progress_callback)
        elif market_lower == "us":
            return await self._fetch_indices_us(progress_callback)
        return 0

    async def _fetch_indices_krx(
        self,
        progress_callback: Callable[[str], None] | None,
    ) -> int:
        try:
            from pykrx import stock as pykrx_stock
        except ImportError:
            return 0

        loop = asyncio.get_event_loop()
        today = datetime.now()
        fromdate = (today - timedelta(days=365)).strftime("%Y%m%d")
        todate = today.strftime("%Y%m%d")
        loaded = 0

        for ticker_code, market_label in [("1001", "KOSPI"), ("2001", "KOSDAQ")]:
            symbol = f"^{market_label}"
            try:
                if progress_callback:
                    progress_callback(f"시장지수 수집: {symbol}")

                df = await loop.run_in_executor(
                    None,
                    lambda tc=ticker_code, f=fromdate, t=todate: pykrx_stock.get_index_ohlcv_by_date(f, t, tc),
                )
                await asyncio.sleep(KRX_RATE_DELAY)

                if df is None or df.empty:
                    continue

                stock = await self._stock_repo.get_or_create(
                    symbol=symbol, name=f"{market_label} Index", market=market_label,
                )

                prices = []
                for date_val, row in df.iterrows():
                    prices.append({
                        "date": date_val.to_pydatetime(),
                        "open": Decimal(str(row.get("시가", 0))),
                        "high": Decimal(str(row.get("고가", 0))),
                        "low": Decimal(str(row.get("저가", 0))),
                        "close": Decimal(str(row.get("종가", 0))),
                        "volume": int(row.get("거래량", 0)),
                    })

                if prices:
                    await self._price_repo.bulk_create(stock.id, prices)
                await self._session.commit()
                loaded += 1

            except Exception as e:
                logger.error("krx_index_error", symbol=symbol, error=str(e))
                await self._session.rollback()

        return loaded

    async def _fetch_indices_us(
        self,
        progress_callback: Callable[[str], None] | None,
    ) -> int:
        try:
            import yfinance as yf
        except ImportError:
            return 0

        loop = asyncio.get_event_loop()
        loaded = 0

        for symbol, market_label in INDEX_SYMBOLS["us"]:
            try:
                if progress_callback:
                    progress_callback(f"시장지수 수집: {symbol}")

                hist = await loop.run_in_executor(
                    None, lambda s=symbol: yf.download(s, period="1y", progress=False),
                )
                await asyncio.sleep(YF_RATE_DELAY)

                if hist is None or hist.empty:
                    continue

                names = {"^GSPC": "S&P 500", "^IXIC": "NASDAQ Composite"}
                stock = await self._stock_repo.get_or_create(
                    symbol=symbol, name=names.get(symbol, symbol), market=market_label,
                )

                prices = self._df_to_us_prices(hist)
                if prices:
                    await self._price_repo.bulk_create(stock.id, prices)
                await self._session.commit()
                loaded += 1

            except Exception as e:
                logger.error("us_index_error", symbol=symbol, error=str(e))
                await self._session.rollback()

        return loaded

    # ── Shares Outstanding + Institutional Data ───────────────

    async def update_stock_metadata(
        self,
        market: str,
        progress_callback: Callable[[str], None] | None = None,
    ) -> int:
        market_lower = market.lower()
        all_stocks = await self._stock_repo.get_all_active(market_lower)
        all_stocks = [s for s in all_stocks if not s.symbol.startswith("^")]

        if not all_stocks:
            return 0

        missing = [s for s in all_stocks if s.shares_outstanding is None]
        if not missing:
            if progress_callback:
                progress_callback(f"{market_lower.upper()} 메타데이터: 전체 수집 완료 상태 (스킵)")
            return 0

        if progress_callback:
            progress_callback(
                f"종목 메타데이터 수집 중 ({market_lower.upper()}, "
                f"미수집 {len(missing)}/{len(all_stocks)}개)..."
            )

        if market_lower == "krx":
            return await self._update_krx_metadata(all_stocks, progress_callback)
        elif market_lower == "us":
            return await self._update_us_metadata(missing, progress_callback)
        return 0

    async def _update_krx_metadata(
        self,
        stocks: list,
        progress_callback: Callable[[str], None] | None,
    ) -> int:
        try:
            from pykrx import stock as pykrx_stock
        except ImportError:
            return 0

        loop = asyncio.get_event_loop()
        today = datetime.now().strftime("%Y%m%d")
        updated = 0
        total = len(stocks)

        try:
            cap_df = await loop.run_in_executor(
                None, lambda: pykrx_stock.get_market_cap_by_ticker(today),
            )
        except Exception as e:
            logger.error("krx_market_cap_error", error=str(e))
            return 0

        if cap_df is None or cap_df.empty:
            return 0

        for i, stock in enumerate(stocks, 1):
            try:
                if stock.symbol in cap_df.index:
                    row = cap_df.loc[stock.symbol]
                    shares = int(row.get("상장주식수", 0))
                    if shares > 0:
                        stock.shares_outstanding = shares
                        updated += 1

                if progress_callback and (i % 200 == 0 or i == total):
                    progress_callback(f"  KRX 메타데이터 [{i}/{total}] (완료: {updated})")

            except Exception as e:
                logger.error("krx_metadata_error", symbol=stock.symbol, error=str(e))

        try:
            await self._session.commit()
        except Exception:
            await self._session.rollback()

        return updated

    async def _update_us_metadata(
        self,
        stocks: list,
        progress_callback: Callable[[str], None] | None,
    ) -> int:
        try:
            import yfinance as yf
        except ImportError:
            return 0

        from concurrent.futures import ThreadPoolExecutor, as_completed

        total = len(stocks)
        updated = 0
        batch_size = 20
        symbol_to_stock = {s.symbol: s for s in stocks}

        def _fetch_info(symbol: str) -> tuple[str, dict | None]:
            try:
                return symbol, yf.Ticker(symbol).info
            except Exception:
                return symbol, None

        if progress_callback:
            progress_callback(f"  US 메타데이터 수집 ({total}개, 병렬 처리)...")

        for batch_start in range(0, total, batch_size):
            batch = stocks[batch_start:batch_start + batch_size]
            batch_syms = [s.symbol for s in batch]

            with ThreadPoolExecutor(max_workers=batch_size) as executor:
                futures = {executor.submit(_fetch_info, sym): sym for sym in batch_syms}
                for future in as_completed(futures):
                    sym, info = future.result()
                    if info is None:
                        continue
                    stock = symbol_to_stock.get(sym)
                    if not stock:
                        continue

                    shares = info.get("sharesOutstanding")
                    if shares:
                        stock.shares_outstanding = int(shares)

                    inst_pct = info.get("heldPercentInstitutions")
                    if inst_pct is not None:
                        stock.institutional_ownership = Decimal(str(round(float(inst_pct), 4)))

                    inst_count = info.get("numberOfInstitutionalHolders")
                    if inst_count is not None:
                        stock.institutional_count = int(inst_count)

                    updated += 1

            processed = min(batch_start + batch_size, total)
            if progress_callback and (processed % 100 == 0 or processed == total):
                progress_callback(f"  US 메타데이터 [{processed}/{total}] (완료: {updated})")

            await asyncio.sleep(0.1)

        try:
            await self._session.commit()
        except Exception:
            await self._session.rollback()

        return updated
