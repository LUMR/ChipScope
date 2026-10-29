"""add alert tables (alert_rule / alert_event)

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-20
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "alert_rule",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("secucodes", postgresql.JSONB(), nullable=False),
        sa.Column("conditions", postgresql.JSONB(), nullable=False),
        sa.Column("cooldown_minutes", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("webhook_url", sa.String(512), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )
    op.create_table(
        "alert_event",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("rule_id", sa.Integer(), nullable=False),
        sa.Column("rule_name", sa.String(64), nullable=False),
        sa.Column("stock_name", sa.String(40), nullable=False),
        sa.Column("secucode", sa.String(12), nullable=False),
        sa.Column(
            "triggered_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column("trade_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["rule_id"], ["alert_rule.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_alert_event_rule_secucode_ts",
        "alert_event", ["rule_id", "secucode", "triggered_at"], unique=False,
    )


def downgrade() -> None:
    op.drop_table("alert_event")
    op.drop_table("alert_rule")
