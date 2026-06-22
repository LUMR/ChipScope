"""add minute_quote

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-22
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "minute_quote",
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("secucode", sa.String(length=12), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["secucode"], ["stock_meta.secucode"],
            name="fk_minute_quote_secucode_stock_meta",
        ),
        sa.PrimaryKeyConstraint("trade_date", "secucode"),
    )
    op.create_index(
        "ix_minute_quote_secucode", "minute_quote", ["secucode"]
    )


def downgrade() -> None:
    op.drop_index("ix_minute_quote_secucode", table_name="minute_quote")
    op.drop_table("minute_quote")
