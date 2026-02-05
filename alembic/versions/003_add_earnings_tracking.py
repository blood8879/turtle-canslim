"""Add earnings tracking fields for period-based freshness detection

Revision ID: 003
Revises: 002
"""
from alembic import op
import sqlalchemy as sa

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("stocks", sa.Column("last_fetched_period", sa.Integer(), nullable=True))
    op.add_column("stocks", sa.Column("last_fetched_at", sa.DateTime(), nullable=True))
    op.add_column("fundamentals", sa.Column("announcement_date", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("fundamentals", "announcement_date")
    op.drop_column("stocks", "last_fetched_at")
    op.drop_column("stocks", "last_fetched_period")
