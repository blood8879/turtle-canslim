#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime

from src.core.config import get_settings, Market
from src.core.database import get_db_manager
from src.core.logger import configure_logging, get_logger
from src.data.repositories import (
    StockRepository,
    FundamentalRepository,
    DailyPriceRepository,
    CANSLIMScoreRepository,
)
from src.screener.canslim import CANSLIMScreener
from src.notification.telegram_bot import TelegramNotifier

logger = get_logger(__name__)


async def run_screening(market: str, min_score: int, notify: bool) -> None:
    logger.info("screening_start", market=market, min_score=min_score)

    db = get_db_manager()
    notifier = TelegramNotifier() if notify else None

    try:
        async with db.session() as session:
            stock_repo = StockRepository(session)
            fundamental_repo = FundamentalRepository(session)
            price_repo = DailyPriceRepository(session)
            score_repo = CANSLIMScoreRepository(session)

            screener = CANSLIMScreener(
                stock_repo=stock_repo,
                fundamental_repo=fundamental_repo,
                price_repo=price_repo,
                score_repo=score_repo,
            )

            results = await screener.screen(market)

            candidates = [r for r in results if r.is_candidate and r.total_score >= min_score]

            print("\n" + "=" * 80)
            print(f"CANSLIM Screening Results - {market.upper()}")
            print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
            print("=" * 80)

            if not candidates:
                print("\nNo candidates found matching criteria.")
            else:
                print(f"\nFound {len(candidates)} candidates:\n")
                print(f"{'Symbol':<12} {'Name':<20} {'Score':<8} {'RS':<6} {'EPS%':<10} {'Rev%':<10}")
                print("-" * 70)

                for r in candidates[:20]:
                    eps_str = f"{float(r.c_eps_growth or 0):.1%}" if r.c_eps_growth else "N/A"
                    rev_str = f"{float(r.c_revenue_growth or 0):.1%}" if r.c_revenue_growth else "N/A"
                    rs_str = str(r.rs_rating) if r.rs_rating else "N/A"

                    print(f"{r.symbol:<12} {r.name[:18]:<20} {r.total_score:<8} {rs_str:<6} {eps_str:<10} {rev_str:<10}")

            print("\n" + "=" * 80)

            if notifier and notifier.is_enabled and candidates:
                message = f"📊 CANSLIM Screening Complete\n\n"
                message += f"Market: {market.upper()}\n"
                message += f"Candidates: {len(candidates)}\n\n"

                for r in candidates[:5]:
                    message += f"• {r.symbol} (Score: {r.total_score}, RS: {r.rs_rating or 'N/A'})\n"

                await notifier.send_message(message)

            logger.info("screening_complete", candidates=len(candidates))

    except Exception as e:
        logger.error("screening_error", error=str(e))
        raise
    finally:
        await db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run CANSLIM screening")
    parser.add_argument(
        "--market",
        "-m",
        choices=["krx", "us", "both"],
        default="krx",
        help="Market to screen (default: krx)",
    )
    parser.add_argument(
        "--min-score",
        "-s",
        type=int,
        default=5,
        help="Minimum CANSLIM score (default: 5)",
    )
    parser.add_argument(
        "--notify",
        "-n",
        action="store_true",
        help="Send Telegram notification",
    )
    parser.add_argument(
        "--log-level",
        "-l",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Log level (default: INFO)",
    )

    args = parser.parse_args()

    configure_logging(level=args.log_level)

    try:
        if args.market == "both":
            asyncio.run(run_screening("krx", args.min_score, args.notify))
            asyncio.run(run_screening("us", args.min_score, args.notify))
        else:
            asyncio.run(run_screening(args.market, args.min_score, args.notify))
    except KeyboardInterrupt:
        print("\nScreening cancelled.")
        sys.exit(0)
    except Exception as e:
        print(f"\nError: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
