"""Data layer module.

Provides API clients and repositories for data access.
"""

from src.data.kis_client import KISClient
from src.data.dart_client import DARTClient, FinancialStatement, CompanyInfo
from src.data.us_client import USMarketClient, USPriceData, USOrderResult
from src.data.sec_edgar_client import SECEdgarClient, USFinancialStatement, USCompanyInfo
from src.data.repositories import (
    StockRepository,
    DailyPriceRepository,
    FundamentalRepository,
    CANSLIMScoreRepository,
    SignalRepository,
    PositionRepository,
    OrderRepository,
    UnitAllocationRepository,
)

__all__ = [
    # API Clients
    "KISClient",
    "DARTClient",
    "USMarketClient",
    "SECEdgarClient",
    # Data classes
    "FinancialStatement",
    "CompanyInfo",
    "USPriceData",
    "USOrderResult",
    "USFinancialStatement",
    "USCompanyInfo",
    # Repositories
    "StockRepository",
    "DailyPriceRepository",
    "FundamentalRepository",
    "CANSLIMScoreRepository",
    "SignalRepository",
    "PositionRepository",
    "OrderRepository",
    "UnitAllocationRepository",
]
