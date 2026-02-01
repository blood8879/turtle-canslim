from __future__ import annotations


class TurtleCANSLIMError(Exception):
    pass


class ConfigurationError(TurtleCANSLIMError):
    pass


class APIError(TurtleCANSLIMError):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class KISAPIError(APIError):
    pass


class DARTAPIError(APIError):
    pass


class SECAPIError(APIError):
    """SEC EDGAR API error."""
    pass


class DataError(TurtleCANSLIMError):
    pass


class InsufficientDataError(DataError):
    def __init__(self, symbol: str, required: int, available: int):
        super().__init__(
            f"Insufficient data for {symbol}: required {required}, available {available}"
        )
        self.symbol = symbol
        self.required = required
        self.available = available


class DataNotFoundError(DataError):
    def __init__(self, entity: str, identifier: str):
        super().__init__(f"{entity} not found: {identifier}")
        self.entity = entity
        self.identifier = identifier


class TradingError(TurtleCANSLIMError):
    pass


class OrderError(TradingError):
    def __init__(self, message: str, order_id: str | None = None):
        super().__init__(message)
        self.order_id = order_id


class InsufficientFundsError(TradingError):
    def __init__(self, required: float, available: float):
        super().__init__(f"Insufficient funds: required {required:,.0f}, available {available:,.0f}")
        self.required = required
        self.available = available


class UnitLimitExceededError(TradingError):
    def __init__(self, limit_type: str, current: int, maximum: int):
        super().__init__(f"{limit_type} unit limit exceeded: {current}/{maximum}")
        self.limit_type = limit_type
        self.current = current
        self.maximum = maximum


class PositionNotFoundError(TradingError):
    def __init__(self, symbol: str):
        super().__init__(f"Position not found: {symbol}")
        self.symbol = symbol


class ScreeningError(TurtleCANSLIMError):
    pass


class SignalError(TurtleCANSLIMError):
    pass


class DatabaseError(TurtleCANSLIMError):
    pass


class NotificationError(TurtleCANSLIMError):
    pass
