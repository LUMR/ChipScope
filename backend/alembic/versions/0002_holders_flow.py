"""holders and money_flow tables

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "top_holders",
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("secucode", sa.String(12), nullable=False),
        sa.Column("rank", sa.SmallInteger(), nullable=False),
        sa.Column("holder_name", sa.String(100)),
        sa.Column("hold_num", sa.BigInteger()),
        sa.Column("hold_ratio", sa.Numeric(8, 4)),
        sa.Column("change_num", sa.BigInteger()),
        sa.Column("holder_type", sa.String(20)),
        sa.PrimaryKeyConstraint("secucode", "ts", "rank"),
    )
    op.create_table(
        "holder_summary",
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("secucode", sa.String(12), nullable=False),
        sa.Column("top10_ratio", sa.Numeric(8, 4)),
        sa.Column("decay_coeff", sa.Numeric(6, 2)),
        sa.Column("float_shares", sa.BigInteger()),
        sa.PrimaryKeyConstraint("secucode", "ts"),
    )
    op.create_table(
        "money_flow",
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("secucode", sa.String(12), nullable=False),
        sa.Column("main_net", sa.Numeric(18, 2)),
        sa.Column("super_large_net", sa.Numeric(18, 2)),
        sa.Column("large_net", sa.Numeric(18, 2)),
        sa.Column("medium_net", sa.Numeric(18, 2)),
        sa.Column("small_net", sa.Numeric(18, 2)),
        sa.PrimaryKeyConstraint("secucode", "ts"),
    )


def downgrade() -> None:
    op.drop_table("money_flow")
    op.drop_table("holder_summary")
    op.drop_table("top_holders")
