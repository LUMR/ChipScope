from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Numeric, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class TopHolder(Base):
    __tablename__ = "top_holders"

    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    secucode: Mapped[str] = mapped_column(String(12), primary_key=True)
    rank: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    holder_name: Mapped[str] = mapped_column(String(100))
    hold_num: Mapped[int] = mapped_column(BigInteger)
    hold_ratio: Mapped[float] = mapped_column(Numeric(8, 4))
    change_num: Mapped[int] = mapped_column(BigInteger)
    holder_type: Mapped[str | None] = mapped_column(String(20), nullable=True)


class HolderSummary(Base):
    __tablename__ = "holder_summary"

    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    secucode: Mapped[str] = mapped_column(String(12), primary_key=True)
    top10_ratio: Mapped[float] = mapped_column(Numeric(8, 4))
    decay_coeff: Mapped[float] = mapped_column(Numeric(6, 2))
    float_shares: Mapped[int] = mapped_column(BigInteger)
