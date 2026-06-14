from datetime import datetime

from sqlalchemy import DateTime, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class MoneyFlow(Base):
    __tablename__ = "money_flow"

    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    secucode: Mapped[str] = mapped_column(String(12), primary_key=True)
    main_net: Mapped[float] = mapped_column(Numeric(18, 2))
    super_large_net: Mapped[float] = mapped_column(Numeric(18, 2))
    large_net: Mapped[float] = mapped_column(Numeric(18, 2))
    medium_net: Mapped[float] = mapped_column(Numeric(18, 2))
    small_net: Mapped[float] = mapped_column(Numeric(18, 2))
