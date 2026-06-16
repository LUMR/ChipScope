"""add stock_meta.float_shares

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-16
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("stock_meta", sa.Column("float_shares", sa.Numeric(20, 0), nullable=True))


def downgrade() -> None:
    op.drop_column("stock_meta", "float_shares")
