"""add stock_metric

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-27
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "stock_metric",
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("secucode", sa.String(length=12), nullable=False),
        sa.Column("close", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column("open", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column("dif", sa.Numeric(precision=14, scale=6), nullable=False),
        sa.Column("dea", sa.Numeric(precision=14, scale=6), nullable=False),
        sa.Column("hist", sa.Numeric(precision=14, scale=6), nullable=False),
        sa.Column("k", sa.Numeric(precision=8, scale=4), nullable=False),
        sa.Column("d", sa.Numeric(precision=8, scale=4), nullable=False),
        sa.Column("j", sa.Numeric(precision=8, scale=4), nullable=False),
        sa.Column("wr", sa.Numeric(precision=8, scale=4), nullable=False),
        sa.Column("rsi", sa.Numeric(precision=8, scale=4), nullable=False),
        sa.Column("prev_rsi", sa.Numeric(precision=8, scale=4), nullable=False),
        sa.Column("ma5", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column("ma10", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column("ma20", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column("ma60", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column("ma20_prev5", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column("high20_prev", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column("high60_prev", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column("vol_ratio", sa.Numeric(precision=10, scale=4), nullable=False),
        sa.Column("pct5", sa.Numeric(precision=10, scale=4), nullable=False),
        sa.Column("consecutive_green", sa.Integer(), nullable=False),
        sa.Column("pct_change", sa.Numeric(precision=8, scale=4), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("signal_level", sa.String(length=16), nullable=False),
        sa.Column("macd_signal", sa.Integer(), nullable=False),
        sa.Column("kdj_signal", sa.Integer(), nullable=False),
        sa.Column("wr_signal", sa.Integer(), nullable=False),
        sa.Column("rsi_signal", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["secucode"], ["stock_meta.secucode"],
            name="fk_stock_metric_secucode_stock_meta",
        ),
        sa.PrimaryKeyConstraint("trade_date", "secucode", name="pk_stock_metric"),
    )
    op.create_index(
        "ix_stock_metric_secucode_trade_date", "stock_metric",
        ["secucode", "trade_date"], unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_stock_metric_secucode_trade_date", table_name="stock_metric"
    )
    op.drop_table("stock_metric")
