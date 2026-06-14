from datetime import datetime

from pydantic import BaseModel


class ChipOut(BaseModel):
    ts: datetime
    distribution: dict
    concentration: float
    cost_high: float
    cost_low: float
    profit_ratio: float
    avg_cost: float

    model_config = {"from_attributes": True}


class ChipHistoryOut(BaseModel):
    ts: datetime
    profit_ratio: float
    concentration: float
    avg_cost: float

    model_config = {"from_attributes": True}
