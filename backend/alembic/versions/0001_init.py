"""init schema with stock_meta and daily_kline hypertable

Revision ID: 0001
Revises:
Create Date: 2026-06-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb;")

    op.create_table(
        "stock_meta",
        sa.Column("secucode", sa.String(12), primary_key=True),
        sa.Column("code", sa.String(8), nullable=False),
        sa.Column("name", sa.String(40), nullable=False),
        sa.Column("market", sa.String(4), nullable=False),
        sa.Column("secid", sa.String(12), nullable=False),
        sa.Column("list_date", sa.Date(), nullable=True),
        sa.Column("industry", sa.String(40), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "daily_kline",
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("secucode", sa.String(12), nullable=False),
        sa.Column("open", sa.Numeric(10, 3)),
        sa.Column("close", sa.Numeric(10, 3)),
        sa.Column("high", sa.Numeric(10, 3)),
        sa.Column("low", sa.Numeric(10, 3)),
        sa.Column("volume", sa.BigInteger()),
        sa.Column("amount", sa.Numeric(18, 2)),
        sa.Column("turnover_rate", sa.Numeric(8, 4)),
        sa.Column("pct_change", sa.Numeric(8, 4)),
        sa.Column("vwap", sa.Numeric(10, 3)),
        sa.ForeignKeyConstraint(["secucode"], ["stock_meta.secucode"]),
        sa.PrimaryKeyConstraint("secucode", "ts"),
    )
    # TimescaleDB 超表：按 30 天分块
    op.execute(
        "SELECT create_hypertable('daily_kline', 'ts', "
        "chunk_time_interval => INTERVAL '30 days', "
        "if_not_exists => TRUE);"
    )
    op.create_index("ix_daily_kline_ts", "daily_kline", ["ts"])


def downgrade() -> None:
    op.drop_table("daily_kline")
    op.drop_table("stock_meta")
