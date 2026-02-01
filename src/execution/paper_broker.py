from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
import uuid

from src.core.logger import get_logger, get_trading_logger
from src.execution.broker_interface import (
    AccountBalance,
    BrokerInterface,
    BrokerOrder,
    BrokerPosition,
    OrderRequest,
    OrderResponse,
)

logger = get_logger(__name__)
tlog = get_trading_logger()


class PaperBroker(BrokerInterface):
    def __init__(
        self,
        initial_cash: Decimal = Decimal("100000000"),
        price_provider: Any = None,
    ):
        self._initial_cash = initial_cash
        self._cash = initial_cash
        self._positions: dict[str, BrokerPosition] = {}
        self._orders: dict[str, BrokerOrder] = {}
        self._price_provider = price_provider
        self._prices: dict[str, Decimal] = {}
        self._connected = False

    @property
    def is_paper_trading(self) -> bool:
        return True

    async def connect(self) -> bool:
        self._connected = True
        logger.info("paper_broker_connected", initial_cash=float(self._initial_cash))
        return True

    async def disconnect(self) -> None:
        self._connected = False
        logger.info("paper_broker_disconnected")

    def set_price(self, symbol: str, price: Decimal) -> None:
        self._prices[symbol] = price

    async def get_current_price(self, symbol: str) -> Decimal:
        if self._price_provider:
            try:
                data = await self._price_provider.get_current_price(symbol)
                return data.get("price", self._prices.get(symbol, Decimal("0")))
            except Exception:
                pass

        cached = self._prices.get(symbol)
        if cached and cached > 0:
            return cached

        return await self._fetch_yfinance_price(symbol)

    async def _fetch_yfinance_price(self, symbol: str) -> Decimal:
        try:
            import yfinance as yf
            import asyncio

            loop = asyncio.get_event_loop()
            ticker = yf.Ticker(symbol)
            info = await loop.run_in_executor(
                None, lambda: ticker.fast_info
            )
            price = Decimal(str(info.get("lastPrice", 0)))
            if price > 0:
                self._prices[symbol] = price
            return price
        except Exception:
            return Decimal("0")

    async def get_balance(self) -> AccountBalance:
        securities_value = Decimal("0")

        for position in self._positions.values():
            current_price = await self.get_current_price(position.symbol)
            securities_value += current_price * position.quantity

        total_value = self._cash + securities_value

        return AccountBalance(
            total_value=total_value,
            cash_balance=self._cash,
            securities_value=securities_value,
            buying_power=self._cash,
        )

    async def get_positions(self) -> list[BrokerPosition]:
        updated_positions: list[BrokerPosition] = []

        for symbol, position in self._positions.items():
            if position.quantity <= 0:
                continue

            current_price = await self.get_current_price(symbol)
            market_value = current_price * position.quantity
            cost_basis = position.avg_price * position.quantity
            unrealized_pnl = market_value - cost_basis
            unrealized_pnl_pct = (
                (unrealized_pnl / cost_basis) if cost_basis > 0 else Decimal("0")
            )

            updated_positions.append(
                BrokerPosition(
                    symbol=symbol,
                    quantity=position.quantity,
                    avg_price=position.avg_price,
                    current_price=current_price,
                    market_value=market_value,
                    unrealized_pnl=unrealized_pnl,
                    unrealized_pnl_pct=unrealized_pnl_pct,
                )
            )

        return updated_positions

    async def get_position(self, symbol: str) -> BrokerPosition | None:
        if symbol not in self._positions:
            return None

        position = self._positions[symbol]
        if position.quantity <= 0:
            return None

        current_price = await self.get_current_price(symbol)
        market_value = current_price * position.quantity
        cost_basis = position.avg_price * position.quantity
        unrealized_pnl = market_value - cost_basis
        unrealized_pnl_pct = (unrealized_pnl / cost_basis) if cost_basis > 0 else Decimal("0")

        return BrokerPosition(
            symbol=symbol,
            quantity=position.quantity,
            avg_price=position.avg_price,
            current_price=current_price,
            market_value=market_value,
            unrealized_pnl=unrealized_pnl,
            unrealized_pnl_pct=unrealized_pnl_pct,
        )

    async def place_order(self, request: OrderRequest) -> OrderResponse:
        order_id = str(uuid.uuid4())[:8]
        now = datetime.now().isoformat()

        price = request.price
        if request.order_type == "MARKET":
            price = await self.get_current_price(request.symbol)

        if price is None or price <= 0:
            return OrderResponse(
                success=False,
                order_id=None,
                message=f"Invalid price for {request.symbol}",
            )

        if request.side == "BUY":
            required_cash = price * request.quantity
            if required_cash > self._cash:
                tlog.warning(
                    "paper_order_insufficient_funds",
                    symbol=request.symbol,
                    required=float(required_cash),
                    available=float(self._cash),
                    quantity=request.quantity,
                    price=float(price),
                )
                return OrderResponse(
                    success=False,
                    order_id=None,
                    message=f"Insufficient funds: need {required_cash}, have {self._cash}",
                )

            self._cash -= required_cash

            if request.symbol in self._positions:
                existing = self._positions[request.symbol]
                total_cost = (existing.avg_price * existing.quantity) + (price * request.quantity)
                new_quantity = existing.quantity + request.quantity
                new_avg_price = total_cost / new_quantity

                self._positions[request.symbol] = BrokerPosition(
                    symbol=request.symbol,
                    quantity=new_quantity,
                    avg_price=new_avg_price,
                    current_price=price,
                    market_value=price * new_quantity,
                    unrealized_pnl=Decimal("0"),
                    unrealized_pnl_pct=Decimal("0"),
                )
            else:
                self._positions[request.symbol] = BrokerPosition(
                    symbol=request.symbol,
                    quantity=request.quantity,
                    avg_price=price,
                    current_price=price,
                    market_value=price * request.quantity,
                    unrealized_pnl=Decimal("0"),
                    unrealized_pnl_pct=Decimal("0"),
                )

        elif request.side == "SELL":
            if request.symbol not in self._positions:
                tlog.warning(
                    "paper_order_no_position",
                    symbol=request.symbol,
                    side=request.side,
                )
                return OrderResponse(
                    success=False,
                    order_id=None,
                    message=f"No position in {request.symbol}",
                )

            position = self._positions[request.symbol]
            if position.quantity < request.quantity:
                tlog.warning(
                    "paper_order_insufficient_shares",
                    symbol=request.symbol,
                    have=position.quantity,
                    need=request.quantity,
                )
                return OrderResponse(
                    success=False,
                    order_id=None,
                    message=f"Insufficient shares: have {position.quantity}, need {request.quantity}",
                )

            proceeds = price * request.quantity
            self._cash += proceeds

            new_quantity = position.quantity - request.quantity
            if new_quantity > 0:
                self._positions[request.symbol] = BrokerPosition(
                    symbol=request.symbol,
                    quantity=new_quantity,
                    avg_price=position.avg_price,
                    current_price=price,
                    market_value=price * new_quantity,
                    unrealized_pnl=Decimal("0"),
                    unrealized_pnl_pct=Decimal("0"),
                )
            else:
                del self._positions[request.symbol]

        order = BrokerOrder(
            order_id=order_id,
            symbol=request.symbol,
            side=request.side,
            quantity=request.quantity,
            order_type=request.order_type,
            price=price,
            status="FILLED",
            filled_quantity=request.quantity,
            filled_price=price,
            created_at=now,
            updated_at=now,
        )
        self._orders[order_id] = order

        tlog.info(
            "paper_order_filled",
            order_id=order_id,
            symbol=request.symbol,
            side=request.side,
            quantity=request.quantity,
            price=float(price),
            cash_remaining=float(self._cash),
        )

        return OrderResponse(
            success=True,
            order_id=order_id,
            message="Order filled",
        )

    async def cancel_order(self, order_id: str) -> OrderResponse:
        if order_id not in self._orders:
            return OrderResponse(
                success=False,
                order_id=order_id,
                message="Order not found",
            )

        order = self._orders[order_id]
        if order.status == "FILLED":
            return OrderResponse(
                success=False,
                order_id=order_id,
                message="Cannot cancel filled order",
            )

        order.status = "CANCELLED"
        order.updated_at = datetime.now().isoformat()

        return OrderResponse(
            success=True,
            order_id=order_id,
            message="Order cancelled",
        )

    async def get_order_status(self, order_id: str) -> BrokerOrder | None:
        return self._orders.get(order_id)

    async def get_open_orders(self) -> list[BrokerOrder]:
        return [o for o in self._orders.values() if o.status not in ["FILLED", "CANCELLED"]]

    def reset(self) -> None:
        self._cash = self._initial_cash
        self._positions.clear()
        self._orders.clear()
        logger.info("paper_broker_reset")
