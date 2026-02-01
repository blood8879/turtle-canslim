"""Initial schema

Revision ID: 001
Revises:
Create Date: 2026-01-20

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "stocks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("symbol", sa.String(20), unique=True, nullable=False, index=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("market", sa.String(10), nullable=False, index=True),
        sa.Column("sector", sa.String(50)),
        sa.Column("industry", sa.String(50)),
        sa.Column("is_active", sa.Boolean(), default=True),
        sa.Column("created_at", sa.DateTime(), default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), onupdate=sa.func.now()),
    )

    op.create_table(
        "daily_prices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("stock_id", sa.Integer(), sa.ForeignKey("stocks.id"), nullable=False, index=True),
        sa.Column("date", sa.DateTime(), nullable=False, index=True),
        sa.Column("open", sa.Numeric(18, 4), nullable=False),
        sa.Column("high", sa.Numeric(18, 4), nullable=False),
        sa.Column("low", sa.Numeric(18, 4), nullable=False),
        sa.Column("close", sa.Numeric(18, 4), nullable=False),
        sa.Column("volume", sa.Integer(), nullable=False),
        sa.UniqueConstraint("stock_id", "date", name="uq_daily_price_stock_date"),
    )

    op.create_table(
        "fundamentals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("stock_id", sa.Integer(), sa.ForeignKey("stocks.id"), nullable=False, index=True),
        sa.Column("fiscal_year", sa.Integer(), nullable=False),
        sa.Column("fiscal_quarter", sa.Integer()),
        sa.Column("revenue", sa.Numeric(20, 2)),
        sa.Column("operating_income", sa.Numeric(20, 2)),
        sa.Column("net_income", sa.Numeric(20, 2)),
        sa.Column("eps", sa.Numeric(18, 4)),
        sa.Column("total_assets", sa.Numeric(20, 2)),
        sa.Column("total_equity", sa.Numeric(20, 2)),
        sa.Column("roe", sa.Numeric(10, 4)),
        sa.Column("created_at", sa.DateTime(), default=sa.func.now()),
        sa.UniqueConstraint("stock_id", "fiscal_year", "fiscal_quarter", name="uq_fundamental_stock_period"),
    )

    op.create_table(
        "canslim_scores",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("stock_id", sa.Integer(), sa.ForeignKey("stocks.id"), nullable=False, index=True),
        sa.Column("date", sa.DateTime(), nullable=False, index=True),
        sa.Column("c_score", sa.Boolean()),
        sa.Column("a_score", sa.Boolean()),
        sa.Column("n_score", sa.Boolean()),
        sa.Column("s_score", sa.Boolean()),
        sa.Column("l_score", sa.Boolean()),
        sa.Column("i_score", sa.Boolean()),
        sa.Column("m_score", sa.Boolean()),
        sa.Column("total_score", sa.Integer()),
        sa.Column("rs_rating", sa.Integer()),
        sa.Column("c_eps_growth", sa.Numeric(10, 4)),
        sa.Column("c_revenue_growth", sa.Numeric(10, 4)),
        sa.Column("a_eps_growth", sa.Numeric(10, 4)),
        sa.Column("is_candidate", sa.Boolean(), default=False),
        sa.Column("created_at", sa.DateTime(), default=sa.func.now()),
        sa.UniqueConstraint("stock_id", "date", name="uq_canslim_stock_date"),
    )

    op.create_table(
        "signals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("stock_id", sa.Integer(), sa.ForeignKey("stocks.id"), nullable=False, index=True),
        sa.Column("timestamp", sa.DateTime(), nullable=False, index=True),
        sa.Column("signal_type", sa.String(20), nullable=False),
        sa.Column("system", sa.Integer()),
        sa.Column("price", sa.Numeric(18, 4), nullable=False),
        sa.Column("atr_n", sa.Numeric(18, 4)),
        sa.Column("is_executed", sa.Boolean(), default=False),
        sa.Column("created_at", sa.DateTime(), default=sa.func.now()),
    )

    op.create_table(
        "positions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("stock_id", sa.Integer(), sa.ForeignKey("stocks.id"), nullable=False, index=True),
        sa.Column("entry_date", sa.DateTime(), nullable=False),
        sa.Column("entry_price", sa.Numeric(18, 4), nullable=False),
        sa.Column("entry_system", sa.Integer()),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("units", sa.Integer(), default=1),
        sa.Column("stop_loss_price", sa.Numeric(18, 4)),
        sa.Column("stop_loss_type", sa.String(10)),
        sa.Column("status", sa.String(20), default="OPEN", index=True),
        sa.Column("exit_date", sa.DateTime()),
        sa.Column("exit_price", sa.Numeric(18, 4)),
        sa.Column("exit_reason", sa.String(50)),
        sa.Column("pnl", sa.Numeric(18, 4)),
        sa.Column("pnl_percent", sa.Numeric(10, 4)),
        sa.Column("created_at", sa.DateTime(), default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), onupdate=sa.func.now()),
    )

    op.create_table(
        "orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("position_id", sa.Integer(), sa.ForeignKey("positions.id")),
        sa.Column("stock_id", sa.Integer(), sa.ForeignKey("stocks.id"), nullable=False, index=True),
        sa.Column("order_type", sa.String(10), nullable=False),
        sa.Column("order_method", sa.String(20), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("price", sa.Numeric(18, 4)),
        sa.Column("status", sa.String(20), default="PENDING", index=True),
        sa.Column("filled_quantity", sa.Integer(), default=0),
        sa.Column("filled_price", sa.Numeric(18, 4)),
        sa.Column("broker_order_id", sa.String(50)),
        sa.Column("created_at", sa.DateTime(), default=sa.func.now()),
        sa.Column("filled_at", sa.DateTime()),
    )

    op.create_table(
        "unit_allocations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("date", sa.DateTime(), nullable=False, index=True),
        sa.Column("total_units", sa.Integer(), default=0),
        sa.Column("available_units", sa.Integer()),
        sa.Column("sector_allocations", sa.Text()),
        sa.Column("created_at", sa.DateTime(), default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("unit_allocations")
    op.drop_table("orders")
    op.drop_table("positions")
    op.drop_table("signals")
    op.drop_table("canslim_scores")
    op.drop_table("fundamentals")
    op.drop_table("daily_prices")
    op.drop_table("stocks")
