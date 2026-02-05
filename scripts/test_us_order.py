#!/usr/bin/env python3
"""
US Stock Order Test Script
모의투자 계좌에서 MSFT 1주 매수 주문 테스트

Usage:
    # 가격만 조회 (주문 X)
    python scripts/test_us_order.py --price-only

    # 실제 주문 실행
    python scripts/test_us_order.py --execute
"""

from __future__ import annotations

import argparse
import os
import sys
from decimal import Decimal
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()


def get_kis_client(exchange: str = "나스닥"):
    """Create KIS client for US market"""
    from mojito import KoreaInvestment

    app_key = os.getenv("KIS_PAPER_APP_KEY")
    app_secret = os.getenv("KIS_PAPER_APP_SECRET")
    account = os.getenv("KIS_PAPER_ACCOUNT")

    if not all([app_key, app_secret, account]):
        print("❌ KIS API credentials not found in .env")
        print("   Required: KIS_PAPER_APP_KEY, KIS_PAPER_APP_SECRET, KIS_PAPER_ACCOUNT")
        sys.exit(1)

    # Format account number if needed
    if "-" not in account:
        account = f"{account[:8]}-{account[8:]}" if len(account) > 8 else f"{account}-01"
        print(f"⚠️  Account formatted to: {account[:4]}****")

    print(f"🔌 Connecting to KIS API (Paper Trading, {exchange})...")

    client = KoreaInvestment(
        api_key=app_key,
        api_secret=app_secret,
        acc_no=account,
        exchange=exchange,
        mock=True,  # Paper trading
    )

    print(f"✅ Connected! Account: {account[:4]}****")
    return client


def fetch_us_price(client, symbol: str) -> dict:
    """Fetch current US stock price"""
    print(f"\n📈 Fetching {symbol} price...")

    try:
        response = client.fetch_oversea_price(symbol)

        if response.get("rt_cd") != "0":
            print(f"❌ API Error: {response.get('msg1', 'Unknown error')}")
            return {}

        output = response.get("output", {})

        price = Decimal(output.get("last", "0"))
        prev_close = Decimal(output.get("base", "0"))
        change = Decimal(output.get("diff", "0"))
        change_pct = Decimal(output.get("rate", "0"))
        high = Decimal(output.get("high", "0"))
        low = Decimal(output.get("low", "0"))
        volume = int(output.get("tvol", "0"))

        print(f"   Symbol: {symbol}")
        print(f"   Current Price: ${price:.2f}")
        print(f"   Previous Close: ${prev_close:.2f}")
        print(f"   Change: ${change:+.2f} ({change_pct:+.2f}%)")
        print(f"   High/Low: ${high:.2f} / ${low:.2f}")
        print(f"   Volume: {volume:,}")

        return {
            "symbol": symbol,
            "price": price,
            "prev_close": prev_close,
            "change": change,
            "change_pct": change_pct,
            "high": high,
            "low": low,
            "volume": volume,
            "raw": response,
        }
    except Exception as e:
        print(f"❌ Error fetching price: {e}")
        return {}


def place_buy_order(client, symbol: str, quantity: int, price: Decimal) -> dict:
    """Place a limit buy order for US stock"""
    print(f"\n🛒 Placing BUY order...")
    print(f"   Symbol: {symbol}")
    print(f"   Quantity: {quantity}")
    print(f"   Limit Price: ${price:.2f}")
    print(f"   Order Type: Limit (00)")

    try:
        # For limit orders, price needs to be in cents or full dollars depending on API
        # Most APIs expect price as a float/int representing dollars
        response = client.create_oversea_order(
            side="buy",
            symbol=symbol,
            price=float(price),
            quantity=quantity,
            order_type="00",  # Limit order
        )

        rt_cd = response.get("rt_cd")
        msg = response.get("msg1", "")

        if rt_cd == "0":
            output = response.get("output", {})
            order_id = output.get("ODNO", output.get("odno", "N/A"))
            print(f"\n✅ Order Submitted Successfully!")
            print(f"   Order ID: {order_id}")
            print(f"   Message: {msg}")
        else:
            print(f"\n❌ Order Failed!")
            print(f"   Error Code: {rt_cd}")
            print(f"   Message: {msg}")

        print(f"\n📋 Full Response:")
        print(f"   {response}")

        return response

    except Exception as e:
        print(f"❌ Error placing order: {e}")
        import traceback

        traceback.print_exc()
        return {}


def place_sell_order(client, symbol: str, quantity: int, price: Decimal) -> dict:
    """Place a limit sell order for US stock"""
    print(f"\n💰 Placing SELL order...")
    print(f"   Symbol: {symbol}")
    print(f"   Quantity: {quantity}")
    print(f"   Limit Price: ${price:.2f}")
    print(f"   Order Type: Limit (00)")

    try:
        response = client.create_oversea_order(
            side="sell",
            symbol=symbol,
            price=float(price),
            quantity=quantity,
            order_type="00",  # Limit order
        )

        rt_cd = response.get("rt_cd")
        msg = response.get("msg1", "")

        if rt_cd == "0":
            output = response.get("output", {})
            order_id = output.get("ODNO", output.get("odno", "N/A"))
            print(f"\n✅ Sell Order Submitted Successfully!")
            print(f"   Order ID: {order_id}")
            print(f"   Message: {msg}")
        else:
            print(f"\n❌ Sell Order Failed!")
            print(f"   Error Code: {rt_cd}")
            print(f"   Message: {msg}")

        print(f"\n📋 Full Response:")
        print(f"   {response}")

        return response

    except Exception as e:
        print(f"❌ Error placing sell order: {e}")
        import traceback

        traceback.print_exc()
        return {}


def fetch_us_balance(client) -> dict:
    """Fetch overseas account balance"""
    print(f"\n💵 Fetching US account balance...")

    try:
        response = client.fetch_balance_oversea()

        if isinstance(response, dict) and response.get("rt_cd") != "0":
            print(f"❌ API Error: {response.get('msg1', 'Unknown error')}")
            return {}

        print(f"📋 Balance Response:")
        print(f"   {response}")

        return response

    except Exception as e:
        print(f"❌ Error fetching balance: {e}")
        import traceback

        traceback.print_exc()
        return {}


def main():
    parser = argparse.ArgumentParser(description="Test US stock order on paper trading account")
    parser.add_argument("--symbol", default="MSFT", help="Stock symbol (default: MSFT)")
    parser.add_argument("--quantity", type=int, default=1, help="Quantity (default: 1)")
    parser.add_argument(
        "--price-only", action="store_true", help="Only fetch price, don't place order"
    )
    parser.add_argument("--execute", action="store_true", help="Execute the buy order")
    parser.add_argument("--sell", action="store_true", help="Place sell order instead of buy")
    parser.add_argument("--balance", action="store_true", help="Check account balance")
    parser.add_argument("--price", type=float, help="Override limit price (default: current price)")

    args = parser.parse_args()

    print("=" * 60)
    print("  US Stock Order Test - Paper Trading (모의투자)")
    print("=" * 60)

    # Connect to KIS
    client = get_kis_client(exchange="나스닥")

    # Check balance if requested
    if args.balance:
        fetch_us_balance(client)

    # Fetch current price
    price_data = fetch_us_price(client, args.symbol)

    if not price_data:
        print("\n❌ Failed to get price data. Exiting.")
        sys.exit(1)

    if args.price_only:
        print("\n✅ Price check complete. Use --execute to place order.")
        return

    if not args.execute:
        print("\n⚠️  Dry run mode. Use --execute to actually place order.")
        print(
            f"    Command: python scripts/test_us_order.py --execute --symbol {args.symbol} --quantity {args.quantity}"
        )
        return

    # Determine price
    order_price = Decimal(str(args.price)) if args.price else price_data["price"]

    # Place order
    if args.sell:
        result = place_sell_order(client, args.symbol, args.quantity, order_price)
    else:
        result = place_buy_order(client, args.symbol, args.quantity, order_price)

    print("\n" + "=" * 60)
    print("  Test Complete!")
    print("=" * 60)

    if result.get("rt_cd") == "0":
        print("✅ Order was successfully submitted to KIS paper trading!")
        print("   Check your 한국투자증권 모의투자 account to verify.")
    else:
        print("❌ Order submission failed. Check error message above.")


if __name__ == "__main__":
    main()
