"""add watchlist table

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-15
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "watchlist",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("secucode", sa.String(12), nullable=False),
        sa.Column("scope", sa.String(32), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["secucode"], ["stock_meta.secucode"]),
        sa.UniqueConstraint("scope", "secucode", name="uq_watchlist_scope_secucode"),
    )
    op.create_index(
        "ix_watchlist_scope_sort_order", "watchlist", ["scope", "sort_order"]
    )


def downgrade() -> None:
    op.drop_table("watchlist")
