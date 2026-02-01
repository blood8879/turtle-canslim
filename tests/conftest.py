from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import AsyncGenerator, Generator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from src.data.models import Base


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest.fixture
def sample_price_data() -> list[dict]:
    return [
        {"date": "2024-01-01", "open": 50000, "high": 51000, "low": 49000, "close": 50500, "volume": 1000000},
        {"date": "2024-01-02", "open": 50500, "high": 52000, "low": 50000, "close": 51500, "volume": 1200000},
        {"date": "2024-01-03", "open": 51500, "high": 53000, "low": 51000, "close": 52500, "volume": 1100000},
        {"date": "2024-01-04", "open": 52500, "high": 54000, "low": 52000, "close": 53500, "volume": 1300000},
        {"date": "2024-01-05", "open": 53500, "high": 55000, "low": 53000, "close": 54500, "volume": 1400000},
    ] * 12


@pytest.fixture
def sample_fundamental_data() -> list[dict]:
    return [
        {"fiscal_year": 2020, "eps": Decimal("1000"), "revenue": Decimal("1000000000")},
        {"fiscal_year": 2021, "eps": Decimal("1200"), "revenue": Decimal("1200000000")},
        {"fiscal_year": 2022, "eps": Decimal("1500"), "revenue": Decimal("1500000000")},
        {"fiscal_year": 2023, "eps": Decimal("1800"), "revenue": Decimal("1900000000")},
        {"fiscal_year": 2024, "eps": Decimal("2200"), "revenue": Decimal("2400000000")},
    ]
