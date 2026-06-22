"""add pre_close to minute_quote

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-22
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("minute_quote", sa.Column("pre_close", sa.Numeric(12, 3), nullable=True))


def downgrade() -> None:
    op.drop_column("minute_quote", "pre_close")
