from datetime import datetime

from pydantic import BaseModel


class WatchlistItemOut(BaseModel):
    """自选项：股票元数据 + 实时报价（报价可能为空）。"""
    secucode: str
    code: str
    name: str
    industry: str | None = None
    sort_order: int
    created_at: datetime
    price: float | None = None
    pct_change: float | None = None

    model_config = {"from_attributes": True}


class WatchlistCreateRequest(BaseModel):
    secucode: str


class ReorderRequest(BaseModel):
    secucodes: list[str]
