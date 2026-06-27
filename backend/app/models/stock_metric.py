from datetime import date

from sqlalchemy import Date, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class StockMetric(Base):
    """指标物化表：每股每日一行的 compute_indicators 快照 + 派生信号。"""
    __tablename__ = "stock_metric"

    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    secucode: Mapped[str] = mapped_column(
        String(12), ForeignKey("stock_meta.secucode"), primary_key=True
    )
    # compute_indicators 快照
    close: Mapped[float] = mapped_column(Numeric(12, 4))
    open: Mapped[float] = mapped_column(Numeric(12, 4))
    dif: Mapped[float] = mapped_column(Numeric(14, 6))
    dea: Mapped[float] = mapped_column(Numeric(14, 6))
    hist: Mapped[float] = mapped_column(Numeric(14, 6))
    k: Mapped[float] = mapped_column(Numeric(8, 4))
    d: Mapped[float] = mapped_column(Numeric(8, 4))
    j: Mapped[float] = mapped_column(Numeric(8, 4))
    wr: Mapped[float] = mapped_column(Numeric(8, 4))
    rsi: Mapped[float] = mapped_column(Numeric(8, 4))
    prev_rsi: Mapped[float] = mapped_column(Numeric(8, 4))
    ma5: Mapped[float] = mapped_column(Numeric(12, 4))
    ma10: Mapped[float] = mapped_column(Numeric(12, 4))
    ma20: Mapped[float] = mapped_column(Numeric(12, 4))
    ma60: Mapped[float] = mapped_column(Numeric(12, 4))
    ma20_prev5: Mapped[float] = mapped_column(Numeric(12, 4))
    high20_prev: Mapped[float] = mapped_column(Numeric(12, 4))
    high60_prev: Mapped[float] = mapped_column(Numeric(12, 4))
    vol_ratio: Mapped[float] = mapped_column(Numeric(10, 4))
    pct5: Mapped[float] = mapped_column(Numeric(10, 4))
    consecutive_green: Mapped[int] = mapped_column(Integer)
    # 当日涨跌幅（从 daily_kline.pct_change 透传，供 screener 显示，非 compute_indicators 字段）
    pct_change: Mapped[float] = mapped_column(Numeric(8, 4))
    # 派生信号
    score: Mapped[int] = mapped_column(Integer)
    signal_level: Mapped[str] = mapped_column(String(16))
    macd_signal: Mapped[int] = mapped_column(Integer)
    kdj_signal: Mapped[int] = mapped_column(Integer)
    wr_signal: Mapped[int] = mapped_column(Integer)
    rsi_signal: Mapped[int] = mapped_column(Integer)
