from datetime import datetime

from sqlalchemy import DateTime, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ChipDistribution(Base):
    __tablename__ = "chip_distribution"

    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    secucode: Mapped[str] = mapped_column(String(12), primary_key=True)
    distribution: Mapped[dict] = mapped_column(JSONB)  # {"15.00": 0.08, ...} ratio
    decay_coeff: Mapped[float] = mapped_column(Numeric(6, 2))
    concentration: Mapped[float] = mapped_column(Numeric(8, 4))  # 90%集中度
    cost_high: Mapped[float] = mapped_column(Numeric(10, 3))
    cost_low: Mapped[float] = mapped_column(Numeric(10, 3))
    profit_ratio: Mapped[float] = mapped_column(Numeric(8, 4))
    avg_cost: Mapped[float] = mapped_column(Numeric(10, 3))
