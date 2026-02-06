"""SEC EDGAR API client for US company financial statements.

SEC EDGAR provides free access to company filings (10-K, 10-Q).
Uses the newer JSON/XBRL APIs for structured data retrieval.

API Documentation: https://www.sec.gov/developer
Rate Limit: 10 requests per second
User-Agent: Required (company name + email)
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from decimal import Decimal
from typing import Any

import httpx

from src.core.config import get_settings
from src.core.exceptions import SECAPIError
from src.core.logger import get_logger

logger = get_logger(__name__)

SEC_DATA_URL = "https://data.sec.gov"
SEC_WWW_URL = "https://www.sec.gov"

# Rate limit: 10 requests per second
RATE_LIMIT_DELAY = 0.1


class USFinancialStatement:
    """US company financial statement data from SEC filings."""

    def __init__(
        self,
        fiscal_year: int,
        fiscal_quarter: int | None,
        form_type: str,  # 10-K, 10-Q
        filed_date: datetime | None,
        revenue: Decimal | None,
        operating_income: Decimal | None,
        net_income: Decimal | None,
        eps: Decimal | None,
        eps_diluted: Decimal | None,
        total_assets: Decimal | None,
        total_equity: Decimal | None,
        shares_outstanding: int | None,
        roe: Decimal | None,
    ):
        self.fiscal_year = fiscal_year
        self.fiscal_quarter = fiscal_quarter
        self.form_type = form_type
        self.filed_date = filed_date
        self.revenue = revenue
        self.operating_income = operating_income
        self.net_income = net_income
        self.eps = eps
        self.eps_diluted = eps_diluted
        self.total_assets = total_assets
        self.total_equity = total_equity
        self.shares_outstanding = shares_outstanding
        self.roe = roe


class USCompanyInfo:
    """US company basic information from SEC."""

    def __init__(
        self,
        cik: str,
        ticker: str,
        name: str,
        exchange: str | None,
        sic: str | None,  # Standard Industrial Classification
        sic_description: str | None,
        fiscal_year_end: str | None,
    ):
        self.cik = cik
        self.ticker = ticker
        self.name = name
        self.exchange = exchange
        self.sic = sic
        self.sic_description = sic_description
        self.fiscal_year_end = fiscal_year_end


class SECEdgarClient:
    """SEC EDGAR API client for retrieving US company financial data.

    Features:
    - Ticker to CIK mapping
    - Company facts (XBRL structured data)
    - 10-K (annual) and 10-Q (quarterly) financial extraction
    - EPS, Revenue, Net Income, ROE calculation

    Usage:
        client = SECEdgarClient()
        financials = await client.get_financial_statements("AAPL", years=5)
    """

    # XBRL taxonomy mappings for US GAAP concepts
    GAAP_CONCEPTS = {
        # Revenue
        "revenue": [
            "us-gaap:Revenues",
            "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
            "us-gaap:SalesRevenueNet",
            "us-gaap:SalesRevenueGoodsNet",
            "us-gaap:RevenueFromContractWithCustomerIncludingAssessedTax",
        ],
        # Operating Income
        "operating_income": [
            "us-gaap:OperatingIncomeLoss",
            "us-gaap:IncomeLossFromContinuingOperationsBeforeIncomeTaxes",
        ],
        # Net Income
        "net_income": [
            "us-gaap:NetIncomeLoss",
            "us-gaap:ProfitLoss",
            "us-gaap:NetIncomeLossAvailableToCommonStockholdersBasic",
        ],
        # EPS
        "eps": [
            "us-gaap:EarningsPerShareBasic",
            "us-gaap:IncomeLossFromContinuingOperationsPerBasicShare",
        ],
        "eps_diluted": [
            "us-gaap:EarningsPerShareDiluted",
            "us-gaap:IncomeLossFromContinuingOperationsPerDilutedShare",
        ],
        # Balance Sheet
        "total_assets": [
            "us-gaap:Assets",
        ],
        "total_equity": [
            "us-gaap:StockholdersEquity",
            "us-gaap:StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
        ],
        "shares_outstanding": [
            "us-gaap:CommonStockSharesOutstanding",
            "dei:EntityCommonStockSharesOutstanding",
        ],
    }

    def __init__(self, user_agent: str | None = None):
        """Initialize SEC EDGAR client.

        Args:
            user_agent: Required by SEC. Format: "CompanyName contact@email.com"
                       If not provided, uses settings.
        """
        settings = get_settings()
        self._user_agent = user_agent or getattr(
            settings, "sec_user_agent", "TurtleCANSLIM contact@example.com"
        )

        self._client = httpx.AsyncClient(
            timeout=30.0,
            headers={
                "User-Agent": self._user_agent,
                "Accept": "application/json",
            },
        )

        # Cache: ticker -> CIK mapping
        self._ticker_to_cik: dict[str, str] = {}
        self._cik_to_ticker: dict[str, str] = {}
        self._ticker_cache_loaded = False

        # Rate limiting
        self._last_request_time = 0.0

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()

    async def _rate_limit(self) -> None:
        """Enforce SEC rate limit of 10 requests/second."""
        now = asyncio.get_event_loop().time()
        elapsed = now - self._last_request_time
        if elapsed < RATE_LIMIT_DELAY:
            await asyncio.sleep(RATE_LIMIT_DELAY - elapsed)
        self._last_request_time = asyncio.get_event_loop().time()

    async def _request(self, url: str) -> dict[str, Any]:
        """Make rate-limited request to SEC API."""
        await self._rate_limit()

        try:
            response = await self._client.get(url)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error("sec_http_error", url=url, status=e.response.status_code)
            raise SECAPIError(
                f"SEC API HTTP error: {e.response.status_code}", status_code=e.response.status_code
            ) from e
        except httpx.RequestError as e:
            logger.error("sec_request_error", url=url, error=str(e))
            raise SECAPIError(f"SEC API request error: {e}") from e

    async def _load_ticker_mapping(self) -> None:
        """Load ticker to CIK mapping from SEC."""
        if self._ticker_cache_loaded:
            return

        try:
            url = f"{SEC_WWW_URL}/files/company_tickers.json"
            data = await self._request(url)

            for item in data.values():
                ticker = str(item.get("ticker", "")).upper()
                cik = str(item.get("cik_str", "")).zfill(10)

                if ticker and cik:
                    self._ticker_to_cik[ticker] = cik
                    self._cik_to_ticker[cik] = ticker

            self._ticker_cache_loaded = True
            logger.info("sec_ticker_mapping_loaded", count=len(self._ticker_to_cik))

        except Exception as e:
            logger.error("sec_ticker_mapping_error", error=str(e))
            raise SECAPIError(f"Failed to load ticker mapping: {e}") from e

    async def get_cik(self, ticker: str) -> str:
        """Convert ticker symbol to CIK (Central Index Key).

        Args:
            ticker: Stock ticker symbol (e.g., "AAPL")

        Returns:
            CIK padded to 10 digits (e.g., "0000320193")
        """
        await self._load_ticker_mapping()

        ticker_upper = ticker.upper()
        if ticker_upper not in self._ticker_to_cik:
            raise SECAPIError(f"Ticker not found: {ticker}")

        return self._ticker_to_cik[ticker_upper]

    async def get_company_info(self, ticker: str) -> USCompanyInfo:
        """Get company information from SEC submissions.

        Args:
            ticker: Stock ticker symbol

        Returns:
            USCompanyInfo with company details
        """
        cik = await self.get_cik(ticker)
        url = f"{SEC_DATA_URL}/submissions/CIK{cik}.json"

        try:
            data = await self._request(url)

            return USCompanyInfo(
                cik=cik,
                ticker=ticker.upper(),
                name=data.get("name", ""),
                exchange=data.get("exchanges", [None])[0] if data.get("exchanges") else None,
                sic=data.get("sic"),
                sic_description=data.get("sicDescription"),
                fiscal_year_end=data.get("fiscalYearEnd"),
            )
        except SECAPIError:
            raise
        except Exception as e:
            logger.error("sec_company_info_error", ticker=ticker, error=str(e))
            raise SECAPIError(f"Failed to get company info for {ticker}: {e}") from e

    async def get_company_facts(self, ticker: str) -> dict[str, Any]:
        """Get all XBRL facts for a company.

        This returns the complete companyfacts dataset with all
        historical financial data in structured XBRL format.

        Args:
            ticker: Stock ticker symbol

        Returns:
            Complete companyfacts JSON
        """
        cik = await self.get_cik(ticker)
        url = f"{SEC_DATA_URL}/api/xbrl/companyfacts/CIK{cik}.json"

        try:
            return await self._request(url)
        except SECAPIError:
            raise
        except Exception as e:
            logger.error("sec_company_facts_error", ticker=ticker, error=str(e))
            raise SECAPIError(f"Failed to get company facts for {ticker}: {e}") from e

    def _extract_fact_values(
        self,
        facts: dict[str, Any],
        concept_keys: list[str],
        form_filter: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Extract values for a concept from company facts.

        Args:
            facts: Company facts JSON
            concept_keys: List of XBRL concept keys to try
            form_filter: Optional list of form types to filter (e.g., ["10-K", "10-Q"])

        Returns:
            List of fact values with metadata
        """
        results = []

        us_gaap = facts.get("facts", {}).get("us-gaap", {})
        dei = facts.get("facts", {}).get("dei", {})

        for key in concept_keys:
            # Parse namespace:concept
            if ":" in key:
                namespace, concept = key.split(":", 1)
                source = us_gaap if namespace == "us-gaap" else dei
            else:
                source = us_gaap
                concept = key

            if concept not in source:
                continue

            concept_data = source[concept]
            units = concept_data.get("units", {})

            # Try USD first, then shares, then pure
            for unit_type in ["USD", "shares", "USD/shares", "pure"]:
                if unit_type not in units:
                    continue

                for item in units[unit_type]:
                    form = item.get("form", "")
                    if form_filter and form not in form_filter:
                        continue

                    results.append({
                        "value": item.get("val"),
                        "form": form,
                        "fy": item.get("fy"),
                        "fp": item.get("fp"),  # FY, Q1, Q2, Q3, Q4
                        "filed": item.get("filed"),
                        "end": item.get("end"),
                        "start": item.get("start"),
                    })

            if results:
                break

        return results

    def _get_latest_value(
        self,
        facts: dict[str, Any],
        concept_keys: list[str],
        fiscal_year: int,
        fiscal_period: str = "FY",
        form_filter: list[str] | None = None,
    ) -> Decimal | None:
        """Get the latest value for a specific fiscal period.

        Args:
            facts: Company facts JSON
            concept_keys: XBRL concept keys
            fiscal_year: Target fiscal year
            fiscal_period: FY, Q1, Q2, Q3, Q4
            form_filter: Form types to consider

        Returns:
            Value as Decimal or None
        """
        values = self._extract_fact_values(facts, concept_keys, form_filter)

        # Filter by fiscal year and period
        matching = [
            v for v in values
            if v.get("fy") == fiscal_year and v.get("fp") == fiscal_period
        ]

        if not matching:
            return None

        # Get the most recently filed value
        matching.sort(key=lambda x: x.get("filed", ""), reverse=True)
        val = matching[0].get("value")

        return Decimal(str(val)) if val is not None else None

    async def get_financial_statements(
        self,
        ticker: str,
        years: int = 5,
    ) -> list[USFinancialStatement]:
        """Get annual financial statements for multiple years.

        Args:
            ticker: Stock ticker symbol
            years: Number of years of data to retrieve

        Returns:
            List of USFinancialStatement for each year
        """
        try:
            facts = await self.get_company_facts(ticker)
            current_year = datetime.now().year
            results: list[USFinancialStatement] = []

            for year in range(current_year - years, current_year + 1):
                fs = self._extract_annual_financials(facts, year)
                if fs:
                    results.append(fs)

            logger.info(
                "sec_financials_retrieved",
                ticker=ticker,
                years_found=len(results),
            )

            return results

        except SECAPIError:
            raise
        except Exception as e:
            logger.error("sec_financials_error", ticker=ticker, error=str(e))
            raise SECAPIError(f"Failed to get financials for {ticker}: {e}") from e

    def _extract_annual_financials(
        self,
        facts: dict[str, Any],
        fiscal_year: int,
    ) -> USFinancialStatement | None:
        """Extract annual financial data for a specific year."""
        form_filter = ["10-K"]

        revenue = self._get_latest_value(
            facts, self.GAAP_CONCEPTS["revenue"], fiscal_year, "FY", form_filter
        )
        operating_income = self._get_latest_value(
            facts, self.GAAP_CONCEPTS["operating_income"], fiscal_year, "FY", form_filter
        )
        net_income = self._get_latest_value(
            facts, self.GAAP_CONCEPTS["net_income"], fiscal_year, "FY", form_filter
        )
        eps = self._get_latest_value(
            facts, self.GAAP_CONCEPTS["eps"], fiscal_year, "FY", form_filter
        )
        eps_diluted = self._get_latest_value(
            facts, self.GAAP_CONCEPTS["eps_diluted"], fiscal_year, "FY", form_filter
        )
        total_assets = self._get_latest_value(
            facts, self.GAAP_CONCEPTS["total_assets"], fiscal_year, "FY", form_filter
        )
        total_equity = self._get_latest_value(
            facts, self.GAAP_CONCEPTS["total_equity"], fiscal_year, "FY", form_filter
        )

        # Get shares outstanding (might be in 10-K or DEI)
        shares = self._get_latest_value(
            facts, self.GAAP_CONCEPTS["shares_outstanding"], fiscal_year, "FY", form_filter
        )
        shares_int = int(shares) if shares else None

        # At least need some key data to consider it valid
        if not any([revenue, net_income, eps]):
            return None

        # Calculate ROE if we have the data
        roe = None
        if net_income and total_equity and total_equity != 0:
            roe = net_income / total_equity

        return USFinancialStatement(
            fiscal_year=fiscal_year,
            fiscal_quarter=None,
            form_type="10-K",
            filed_date=None,
            revenue=revenue,
            operating_income=operating_income,
            net_income=net_income,
            eps=eps,
            eps_diluted=eps_diluted,
            total_assets=total_assets,
            total_equity=total_equity,
            shares_outstanding=shares_int,
            roe=roe,
        )

    async def get_quarterly_financials(
        self,
        ticker: str,
        year: int,
        quarter: int,
    ) -> USFinancialStatement | None:
        """Get quarterly financial data.

        Args:
            ticker: Stock ticker symbol
            year: Fiscal year
            quarter: Quarter number (1-4)

        Returns:
            USFinancialStatement or None if not found
        """
        try:
            facts = await self.get_company_facts(ticker)

            fp_map = {1: "Q1", 2: "Q2", 3: "Q3", 4: "Q4"}
            fiscal_period = fp_map.get(quarter, "Q4")
            form_filter = ["10-Q"] if quarter < 4 else ["10-K"]

            revenue = self._get_latest_value(
                facts, self.GAAP_CONCEPTS["revenue"], year, fiscal_period, form_filter
            )
            net_income = self._get_latest_value(
                facts, self.GAAP_CONCEPTS["net_income"], year, fiscal_period, form_filter
            )
            eps = self._get_latest_value(
                facts, self.GAAP_CONCEPTS["eps"], year, fiscal_period, form_filter
            )
            eps_diluted = self._get_latest_value(
                facts, self.GAAP_CONCEPTS["eps_diluted"], year, fiscal_period, form_filter
            )

            if not any([revenue, net_income, eps]):
                return None

            return USFinancialStatement(
                fiscal_year=year,
                fiscal_quarter=quarter,
                form_type="10-Q" if quarter < 4 else "10-K",
                filed_date=None,
                revenue=revenue,
                operating_income=None,
                net_income=net_income,
                eps=eps,
                eps_diluted=eps_diluted,
                total_assets=None,
                total_equity=None,
                shares_outstanding=None,
                roe=None,
            )

        except SECAPIError:
            raise
        except Exception as e:
            logger.error(
                "sec_quarterly_error",
                ticker=ticker,
                year=year,
                quarter=quarter,
                error=str(e),
            )
            raise SECAPIError(f"Failed to get quarterly data for {ticker}: {e}") from e

    async def get_yoy_comparison(
        self,
        ticker: str,
        year: int,
        quarter: int,
    ) -> tuple[USFinancialStatement | None, USFinancialStatement | None]:
        """Get YoY comparison data for CANSLIM C indicator.

        Args:
            ticker: Stock ticker symbol
            year: Current fiscal year
            quarter: Current quarter

        Returns:
            Tuple of (current_quarter, year_ago_quarter)
        """
        current = await self.get_quarterly_financials(ticker, year, quarter)
        year_ago = await self.get_quarterly_financials(ticker, year - 1, quarter)

        return current, year_ago
