"""Add shares_outstanding, institutional_ownership, institutional_count to stocks

Revision ID: 002
Revises: 001
"""
from alembic import op
import sqlalchemy as sa

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("stocks", sa.Column("shares_outstanding", sa.Integer(), nullable=True))
    op.add_column("stocks", sa.Column("institutional_ownership", sa.Numeric(10, 4), nullable=True))
    op.add_column("stocks", sa.Column("institutional_count", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("stocks", "institutional_count")
    op.drop_column("stocks", "institutional_ownership")
    op.drop_column("stocks", "shares_outstanding")
