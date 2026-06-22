from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class MinuteQuote(Base):
    __tablename__ = "minute_quote"

    __table_args__ = (
        Index("ix_minute_quote_secucode", "secucode"),
    )

    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    secucode: Mapped[str] = mapped_column(
        String(12), ForeignKey("stock_meta.secucode"), primary_key=True
    )
    data: Mapped[list] = mapped_column(JSONB)  # [{"t":"09:31","price":..,"vol":..}, ...]
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
