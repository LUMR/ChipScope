from datetime import datetime

from pydantic import BaseModel


class KlineOut(BaseModel):
    ts: datetime
    open: float
    close: float
    high: float
    low: float
    volume: int
    amount: float
    turnover_rate: float
    pct_change: float
    vwap: float

    model_config = {"from_attributes": True}
