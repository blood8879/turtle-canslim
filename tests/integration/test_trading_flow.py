from __future__ import annotations

from decimal import Decimal
from datetime import datetime

import pytest
import pytest_asyncio

from src.core.config import RiskConfig
from src.execution.paper_broker import PaperBroker
from src.execution.broker_interface import OrderRequest
from src.risk.position_sizing import PositionSizer


class TestPaperBrokerFlow:
    @pytest_asyncio.fixture
    async def broker(self) -> PaperBroker:
        broker = PaperBroker(initial_cash=Decimal("100000000"))
        await broker.connect()
        broker.set_price("005930", Decimal("50000"))
        return broker

    @pytest.mark.asyncio
    async def test_buy_market_order(self, broker: PaperBroker) -> None:
        response = await broker.buy_market("005930", 100)

        assert response.success is True
        assert response.order_id is not None

        balance = await broker.get_balance()
        assert balance.cash_balance == Decimal("100000000") - (Decimal("50000") * 100)

    @pytest.mark.asyncio
    async def test_sell_market_order(self, broker: PaperBroker) -> None:
        await broker.buy_market("005930", 100)

        broker.set_price("005930", Decimal("55000"))
        response = await broker.sell_market("005930", 100)

        assert response.success is True

        balance = await broker.get_balance()
        expected = Decimal("100000000") - (Decimal("50000") * 100) + (Decimal("55000") * 100)
        assert balance.cash_balance == expected

    @pytest.mark.asyncio
    async def test_insufficient_funds(self, broker: PaperBroker) -> None:
        response = await broker.buy_market("005930", 10000)

        assert response.success is False
        assert "Insufficient" in response.message

    @pytest.mark.asyncio
    async def test_insufficient_shares(self, broker: PaperBroker) -> None:
        response = await broker.sell_market("005930", 100)

        assert response.success is False
        assert "No position" in response.message

    @pytest.mark.asyncio
    async def test_position_tracking(self, broker: PaperBroker) -> None:
        await broker.buy_market("005930", 100)

        positions = await broker.get_positions()
        assert len(positions) == 1
        assert positions[0].symbol == "005930"
        assert positions[0].quantity == 100

        position = await broker.get_position("005930")
        assert position is not None
        assert position.quantity == 100

    @pytest.mark.asyncio
    async def test_pnl_calculation(self, broker: PaperBroker) -> None:
        await broker.buy_market("005930", 100)

        broker.set_price("005930", Decimal("55000"))

        positions = await broker.get_positions()
        position = positions[0]

        assert position.unrealized_pnl == Decimal("500000")
        assert position.unrealized_pnl_pct == Decimal("0.1")

    @pytest.mark.asyncio
    async def test_multiple_positions(self, broker: PaperBroker) -> None:
        broker.set_price("000660", Decimal("100000"))

        await broker.buy_market("005930", 100)
        await broker.buy_market("000660", 50)

        positions = await broker.get_positions()
        assert len(positions) == 2

        balance = await broker.get_balance()
        expected_cash = Decimal("100000000") - (Decimal("50000") * 100) - (Decimal("100000") * 50)
        assert balance.cash_balance == expected_cash

    @pytest.mark.asyncio
    async def test_averaging_up(self, broker: PaperBroker) -> None:
        await broker.buy_market("005930", 100)

        broker.set_price("005930", Decimal("51000"))
        await broker.buy_market("005930", 100)

        position = await broker.get_position("005930")
        assert position is not None
        assert position.quantity == 200
        assert position.avg_price == Decimal("50500")


class TestPositionSizingIntegration:
    def test_full_trade_cycle(self) -> None:
        config = RiskConfig()
        sizer = PositionSizer(config)

        result = sizer.calculate_full_position(
            account_value=Decimal("100000000"),
            entry_price=Decimal("50000"),
            atr_n=Decimal("1500"),
        )

        assert result.quantity > 0
        assert result.risk_amount <= Decimal("2000000")

        simulated_pnl = (result.stop_loss_price - Decimal("50000")) * result.quantity
        assert simulated_pnl >= -Decimal("2000000")
