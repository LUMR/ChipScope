from datetime import date, datetime

from sqlalchemy import Date, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class StockMeta(Base):
    __tablename__ = "stock_meta"

    secucode: Mapped[str] = mapped_column(String(12), primary_key=True)  # 600519.SH
    code: Mapped[str] = mapped_column(String(8), nullable=False)
    name: Mapped[str] = mapped_column(String(40), nullable=False)
    market: Mapped[str] = mapped_column(String(4), nullable=False)  # SH / SZ / BJ
    secid: Mapped[str] = mapped_column(String(12), nullable=False)  # 1.600519
    list_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    industry: Mapped[str | None] = mapped_column(String(40), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
