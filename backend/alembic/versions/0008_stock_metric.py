"""stock_metric 物化表

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-25
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "stock_metric",
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("secucode", sa.String(12), nullable=False),
        # compute_indicators 快照
        sa.Column("close", sa.Numeric(12, 4)),
        sa.Column("open", sa.Numeric(12, 4)),
        sa.Column("dif", sa.Numeric(14, 6)),
        sa.Column("dea", sa.Numeric(14, 6)),
        sa.Column("hist", sa.Numeric(14, 6)),
        sa.Column("k", sa.Numeric(8, 4)),
        sa.Column("d", sa.Numeric(8, 4)),
        sa.Column("j", sa.Numeric(8, 4)),
        sa.Column("wr", sa.Numeric(8, 4)),
        sa.Column("rsi", sa.Numeric(8, 4)),
        sa.Column("prev_rsi", sa.Numeric(8, 4)),
        sa.Column("ma5", sa.Numeric(12, 4)),
        sa.Column("ma10", sa.Numeric(12, 4)),
        sa.Column("ma20", sa.Numeric(12, 4)),
        sa.Column("ma60", sa.Numeric(12, 4)),
        sa.Column("ma20_prev5", sa.Numeric(12, 4)),
        sa.Column("high20_prev", sa.Numeric(12, 4)),
        sa.Column("high60_prev", sa.Numeric(12, 4)),
        sa.Column("vol_ratio", sa.Numeric(10, 4)),
        sa.Column("pct5", sa.Numeric(10, 4)),
        sa.Column("consecutive_green", sa.Integer()),
        sa.Column("pct_change", sa.Numeric(8, 4)),
        # 派生信号
        sa.Column("score", sa.Integer()),
        sa.Column("signal_level", sa.String(16)),
        sa.Column("macd_signal", sa.Integer()),
        sa.Column("kdj_signal", sa.Integer()),
        sa.Column("wr_signal", sa.Integer()),
        sa.Column("rsi_signal", sa.Integer()),
        sa.ForeignKeyConstraint(["secucode"], ["stock_meta.secucode"]),
        sa.PrimaryKeyConstraint("trade_date", "secucode"),
    )
    op.create_index(
        "ix_stock_metric_secucode_trade_date",
        "stock_metric", ["secucode", "trade_date"], unique=False,
    )


def downgrade() -> None:
    op.drop_table("stock_metric")
