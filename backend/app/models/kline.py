from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class DailyKline(Base):
    __tablename__ = "daily_kline"

    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    secucode: Mapped[str] = mapped_column(
        String(12), ForeignKey("stock_meta.secucode"), primary_key=True
    )
    open: Mapped[float] = mapped_column(Numeric(10, 3))
    close: Mapped[float] = mapped_column(Numeric(10, 3))
    high: Mapped[float] = mapped_column(Numeric(10, 3))
    low: Mapped[float] = mapped_column(Numeric(10, 3))
    volume: Mapped[int] = mapped_column(BigInteger)  # 成交量(手)
    amount: Mapped[float] = mapped_column(Numeric(18, 2))  # 成交额(元)
    turnover_rate: Mapped[float] = mapped_column(Numeric(8, 4))  # 换手率% (东财 f61)
    pct_change: Mapped[float] = mapped_column(Numeric(8, 4))  # 涨跌幅% (东财 f59)
    vwap: Mapped[float] = mapped_column(Numeric(10, 3))  # 均价 = amount/vol/100
