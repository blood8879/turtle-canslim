from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from typing import Any


@dataclass
class AccountBalance:
    total_value: Decimal
    cash_balance: Decimal
    securities_value: Decimal
    buying_power: Decimal


@dataclass
class BrokerPosition:
    symbol: str
    quantity: int
    avg_price: Decimal
    current_price: Decimal
    market_value: Decimal
    unrealized_pnl: Decimal
    unrealized_pnl_pct: Decimal


@dataclass
class BrokerOrder:
    order_id: str
    symbol: str
    side: str
    quantity: int
    order_type: str
    price: Decimal | None
    status: str
    filled_quantity: int
    filled_price: Decimal | None
    created_at: str
    updated_at: str | None


@dataclass
class OrderRequest:
    symbol: str
    side: str
    quantity: int
    order_type: str = "MARKET"
    price: Decimal | None = None


@dataclass
class OrderResponse:
    success: bool
    order_id: str | None
    message: str
    raw_response: dict[str, Any] | None = None


class BrokerInterface(ABC):
    @abstractmethod
    async def connect(self) -> bool:
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        pass

    @abstractmethod
    async def get_balance(self) -> AccountBalance:
        pass

    @abstractmethod
    async def get_positions(self) -> list[BrokerPosition]:
        pass

    @abstractmethod
    async def get_position(self, symbol: str) -> BrokerPosition | None:
        pass

    @abstractmethod
    async def place_order(self, request: OrderRequest) -> OrderResponse:
        pass

    @abstractmethod
    async def cancel_order(self, order_id: str) -> OrderResponse:
        pass

    @abstractmethod
    async def get_order_status(self, order_id: str) -> BrokerOrder | None:
        pass

    @abstractmethod
    async def get_open_orders(self) -> list[BrokerOrder]:
        pass

    @abstractmethod
    async def get_current_price(self, symbol: str) -> Decimal:
        pass

    @property
    @abstractmethod
    def is_paper_trading(self) -> bool:
        pass

    async def buy_market(self, symbol: str, quantity: int) -> OrderResponse:
        return await self.place_order(
            OrderRequest(symbol=symbol, side="BUY", quantity=quantity, order_type="MARKET")
        )

    async def sell_market(self, symbol: str, quantity: int) -> OrderResponse:
        return await self.place_order(
            OrderRequest(symbol=symbol, side="SELL", quantity=quantity, order_type="MARKET")
        )

    async def buy_limit(self, symbol: str, quantity: int, price: Decimal) -> OrderResponse:
        return await self.place_order(
            OrderRequest(
                symbol=symbol, side="BUY", quantity=quantity, order_type="LIMIT", price=price
            )
        )

    async def sell_limit(self, symbol: str, quantity: int, price: Decimal) -> OrderResponse:
        return await self.place_order(
            OrderRequest(
                symbol=symbol, side="SELL", quantity=quantity, order_type="LIMIT", price=price
            )
        )
