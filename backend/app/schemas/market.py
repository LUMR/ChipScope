from pydantic import BaseModel


class OverviewPointOut(BaseModel):
    t: str
    avg_pct: float | None
    up: int
    limit_up: int
    flat: int
    down: int
    limit_down: int


class OverviewSummaryOut(BaseModel):
    total: int
    with_pre_close: int
    up: int
    limit_up: int
    flat: int
    down: int
    limit_down: int


class OverviewOut(BaseModel):
    trade_date: str
    series: list[OverviewPointOut]
    summary: OverviewSummaryOut


class RankItemOut(BaseModel):
    secucode: str
    name: str
    price: float
    pct: float


class RankingOut(BaseModel):
    time: str
    gainers: list[RankItemOut]
    losers: list[RankItemOut]


class StockMinutePointOut(BaseModel):
    t: str
    price: float
    vol: int
    pct: float | None


class StockMinuteOut(BaseModel):
    secucode: str
    name: str
    pre_close: float | None
    points: list[StockMinutePointOut]
