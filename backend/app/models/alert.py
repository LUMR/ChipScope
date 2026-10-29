from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AlertRule(Base):
    __tablename__ = "alert_rule"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    secucodes: Mapped[list] = mapped_column(JSONB)  # ["600519.SH", ...]
    conditions: Mapped[list] = mapped_column(JSONB)  # 条件数组，AND 语义
    cooldown_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    webhook_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AlertEvent(Base):
    __tablename__ = "alert_event"
    __table_args__ = (
        Index("ix_alert_event_rule_secucode_ts", "rule_id", "secucode", "triggered_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rule_id: Mapped[int] = mapped_column(
        ForeignKey("alert_rule.id", ondelete="CASCADE"), nullable=False
    )
    # 名称快照：规则改名/股票更名后历史事件仍可读
    rule_name: Mapped[str] = mapped_column(String(64), nullable=False)
    stock_name: Mapped[str] = mapped_column(String(40), nullable=False)
    secucode: Mapped[str] = mapped_column(String(12), nullable=False)
    triggered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    trade_date: Mapped[date | None] = mapped_column(Date, nullable=True)  # 日级去重键
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    payload: Mapped[dict] = mapped_column(JSONB)  # 触发时刻指标快照
    message: Mapped[str] = mapped_column(Text, nullable=False)  # 渲染好的 markdown 快照
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)  # 失败原因
