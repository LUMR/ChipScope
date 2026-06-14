from datetime import datetime

from pydantic import BaseModel


class FlowOut(BaseModel):
    ts: datetime
    main_net: float
    super_large_net: float
    large_net: float
    medium_net: float
    small_net: float

    model_config = {"from_attributes": True}
