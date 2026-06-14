"""chip_distribution table

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "chip_distribution",
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("secucode", sa.String(12), nullable=False),
        sa.Column("distribution", postgresql.JSONB),
        sa.Column("decay_coeff", sa.Numeric(6, 2)),
        sa.Column("concentration", sa.Numeric(8, 4)),
        sa.Column("cost_high", sa.Numeric(10, 3)),
        sa.Column("cost_low", sa.Numeric(10, 3)),
        sa.Column("profit_ratio", sa.Numeric(8, 4)),
        sa.Column("avg_cost", sa.Numeric(10, 3)),
        sa.PrimaryKeyConstraint("secucode", "ts"),
    )
    op.execute(
        "CREATE INDEX idx_chip_dist_gin ON chip_distribution USING GIN (distribution);"
    )


def downgrade() -> None:
    op.drop_table("chip_distribution")
