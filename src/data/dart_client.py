from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from typing import Any

import httpx

from src.core.config import get_settings
from src.core.exceptions import DARTAPIError
from src.core.logger import get_logger

logger = get_logger(__name__)

DART_BASE_URL = "https://opendart.fss.or.kr/api"

REPORT_CODES = {
    "annual": "11011",
    "q1": "11013",
    "half": "11012",
    "q3": "11014",
}

REPORT_DETAIL_TYPES = {
    "A001": 4,
    "A002": 2,
    "A003": None,
}


class FinancialStatement:
    def __init__(
        self,
        fiscal_year: int,
        fiscal_quarter: int | None,
        revenue: Decimal | None,
        operating_income: Decimal | None,
        net_income: Decimal | None,
        eps: Decimal | None,
        total_assets: Decimal | None,
        total_equity: Decimal | None,
        roe: Decimal | None,
    ):
        self.fiscal_year = fiscal_year
        self.fiscal_quarter = fiscal_quarter
        self.revenue = revenue
        self.operating_income = operating_income
        self.net_income = net_income
        self.eps = eps
        self.total_assets = total_assets
        self.total_equity = total_equity
        self.roe = roe


class CompanyInfo:
    def __init__(
        self,
        corp_code: str,
        corp_name: str,
        stock_code: str | None,
        ceo_name: str | None,
        corp_cls: str | None,
        est_dt: str | None,
        acc_mt: str | None,
    ):
        self.corp_code = corp_code
        self.corp_name = corp_name
        self.stock_code = stock_code
        self.ceo_name = ceo_name
        self.corp_cls = corp_cls
        self.est_dt = est_dt
        self.acc_mt = acc_mt


class DARTClient:
    def __init__(self, api_key: str | None = None):
        settings = get_settings()
        self._api_key = api_key or settings.dart_api_key

        if not self._api_key:
            raise DARTAPIError("DART API key not configured")

        self._client = httpx.AsyncClient(
            base_url=DART_BASE_URL,
            timeout=30.0,
        )
        self._corp_code_cache: dict[str, str] = {}

    async def close(self) -> None:
        await self._client.aclose()

    async def _request(self, endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
        params["crtfc_key"] = self._api_key

        try:
            response = await self._client.get(endpoint, params=params)
            response.raise_for_status()
            data = response.json()

            status = data.get("status")
            if status and status != "000":
                message = data.get("message", "Unknown error")
                logger.error("dart_api_error", endpoint=endpoint, status=status, message=message)
                raise DARTAPIError(f"DART API error: {message}", status_code=int(status))

            return data
        except httpx.HTTPStatusError as e:
            logger.error("dart_http_error", endpoint=endpoint, status=e.response.status_code)
            raise DARTAPIError(
                f"DART API HTTP error: {e.response.status_code}", status_code=e.response.status_code
            ) from e
        except httpx.RequestError as e:
            logger.error("dart_request_error", endpoint=endpoint, error=str(e))
            raise DARTAPIError(f"DART API request error: {e}") from e

    async def get_corp_code(self, stock_code: str) -> str:
        if stock_code in self._corp_code_cache:
            return self._corp_code_cache[stock_code]

        try:
            data = await self._request("/company.json", {"corp_code": stock_code})
            corp_code = data.get("corp_code", "")

            if not corp_code:
                companies = await self.search_company(stock_code)
                for company in companies:
                    if company.stock_code == stock_code:
                        corp_code = company.corp_code
                        break

            if corp_code:
                self._corp_code_cache[stock_code] = corp_code

            return corp_code
        except DARTAPIError:
            raise
        except Exception as e:
            logger.error("dart_get_corp_code_error", stock_code=stock_code, error=str(e))
            raise DARTAPIError(f"Failed to get corp code for {stock_code}: {e}") from e

    async def search_company(self, keyword: str) -> list[CompanyInfo]:
        try:
            data = await self._request("/company.json", {"corp_code": keyword})

            if "list" not in data:
                if data.get("corp_code"):
                    return [
                        CompanyInfo(
                            corp_code=data.get("corp_code", ""),
                            corp_name=data.get("corp_name", ""),
                            stock_code=data.get("stock_code"),
                            ceo_name=data.get("ceo_nm"),
                            corp_cls=data.get("corp_cls"),
                            est_dt=data.get("est_dt"),
                            acc_mt=data.get("acc_mt"),
                        )
                    ]
                return []

            return [
                CompanyInfo(
                    corp_code=item.get("corp_code", ""),
                    corp_name=item.get("corp_name", ""),
                    stock_code=item.get("stock_code"),
                    ceo_name=item.get("ceo_nm"),
                    corp_cls=item.get("corp_cls"),
                    est_dt=item.get("est_dt"),
                    acc_mt=item.get("acc_mt"),
                )
                for item in data.get("list", [])
            ]
        except DARTAPIError:
            raise
        except Exception as e:
            logger.error("dart_search_company_error", keyword=keyword, error=str(e))
            raise DARTAPIError(f"Failed to search company: {e}") from e

    async def get_financial_statements(
        self,
        corp_code: str,
        year: int,
        report_type: str = "annual",
    ) -> FinancialStatement | None:
        report_code = REPORT_CODES.get(report_type, "11011")
        fiscal_quarter = None if report_type == "annual" else {"q1": 1, "half": 2, "q3": 3}.get(
            report_type
        )

        try:
            data = await self._request(
                "/fnlttSinglAcntAll.json",
                {
                    "corp_code": corp_code,
                    "bsns_year": str(year),
                    "reprt_code": report_code,
                    "fs_div": "CFS",
                },
            )

            items = data.get("list", [])
            if not items:
                data = await self._request(
                    "/fnlttSinglAcntAll.json",
                    {
                        "corp_code": corp_code,
                        "bsns_year": str(year),
                        "reprt_code": report_code,
                        "fs_div": "OFS",
                    },
                )
                items = data.get("list", [])

            if not items:
                return None

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
                        except Exception:
                            pass

            roe = None
            if financials["net_income"] and financials["total_equity"]:
                equity = financials["total_equity"]
                if equity and equity != 0:
                    roe = financials["net_income"] / equity

            return FinancialStatement(
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

        except DARTAPIError:
            raise
        except Exception as e:
            logger.error(
                "dart_financial_statements_error",
                corp_code=corp_code,
                year=year,
                error=str(e),
            )
            raise DARTAPIError(f"Failed to get financial statements: {e}") from e

    async def get_quarterly_financials(
        self,
        corp_code: str,
        year: int,
        quarter: int,
    ) -> FinancialStatement | None:
        report_type_map = {1: "q1", 2: "half", 3: "q3", 4: "annual"}
        report_type = report_type_map.get(quarter, "annual")
        return await self.get_financial_statements(corp_code, year, report_type)

    async def get_multi_year_financials(
        self,
        corp_code: str,
        years: int = 5,
    ) -> list[FinancialStatement]:
        current_year = datetime.now().year
        results: list[FinancialStatement] = []

        for year in range(current_year - years, current_year + 1):
            try:
                fs = await self.get_financial_statements(corp_code, year, "annual")
                if fs:
                    results.append(fs)
            except DARTAPIError:
                continue

        return results

    async def get_disclosure_list(
        self,
        corp_code: str,
        bgn_de: str | None = None,
        end_de: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "corp_code": corp_code,
            "pblntf_ty": "A",
            "page_count": "100",
        }
        if bgn_de:
            params["bgn_de"] = bgn_de
        if end_de:
            params["end_de"] = end_de

        try:
            data = await self._request("/list.json", params)
            return data.get("list", [])
        except DARTAPIError as e:
            if e.status_code == 13:
                return []
            raise

    async def get_latest_available_period(
        self,
        corp_code: str,
    ) -> tuple[int | None, datetime | None]:
        now = datetime.now()
        bgn_de = f"{now.year - 1}0101"
        end_de = now.strftime("%Y%m%d")

        disclosures = await self.get_disclosure_list(corp_code, bgn_de, end_de)
        if not disclosures:
            return None, None

        latest_period = 0
        latest_date: datetime | None = None

        for item in disclosures:
            report_nm = item.get("report_nm", "")
            rcept_dt = item.get("rcept_dt", "")

            if "[정정]" in report_nm:
                continue

            period = self._extract_period_from_report_name(report_nm)
            if period and period > latest_period:
                latest_period = period
                if rcept_dt:
                    latest_date = datetime.strptime(rcept_dt, "%Y%m%d")

        return (latest_period, latest_date) if latest_period > 0 else (None, None)

    @staticmethod
    def _extract_period_from_report_name(report_nm: str) -> int | None:
        if "사업보고서" in report_nm:
            year_match = re.search(r"\((\d{4})", report_nm)
            if year_match:
                return int(year_match.group(1)) * 10 + 4
        elif "반기보고서" in report_nm:
            year_match = re.search(r"\((\d{4})", report_nm)
            if year_match:
                return int(year_match.group(1)) * 10 + 2
        elif "분기보고서" in report_nm:
            year_match = re.search(r"\((\d{4})\.(\d{2})\)", report_nm)
            if year_match:
                year = int(year_match.group(1))
                month = int(year_match.group(2))
                if month <= 3:
                    return year * 10 + 1
                elif month <= 9:
                    return year * 10 + 3
        return None

    @staticmethod
    def period_to_year_quarter(period: int) -> tuple[int, int]:
        year = period // 10
        quarter = period % 10
        return year, quarter
