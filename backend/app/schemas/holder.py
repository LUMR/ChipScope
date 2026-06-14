from datetime import datetime

from pydantic import BaseModel


class HolderOut(BaseModel):
    ts: datetime
    rank: int
    holder_name: str
    hold_ratio: float
    hold_num: int

    model_config = {"from_attributes": True}
