"""选股筛选器请求/响应模型。"""
from pydantic import BaseModel


class ExtraCondition(BaseModel):
    """辅助条件（见 indicator.evaluate_extras）。

    type ∈ {ma_bull, above_ma, ma_up, breakout, new_high,
            volume_up, volume_up_green, pct_range, consecutive_green}
    n / k / lo / hi 按 type 取用，缺省由 evaluate_extras 解释。
    """
    type: str
    n: int | None = None
    k: float | None = None
    lo: float | None = None
    hi: float | None = None


class ScreenRequest(BaseModel):
    signal: str | None = None  # strong_bull/bull/neutral/bear/strong_bear；缺省不过滤
    extras: list[ExtraCondition] = []
    sort: str = "score_desc"  # 仅 score_desc / 其他视为升序


class ScreenItem(BaseModel):
    secucode: str
    name: str
    close: float
    pct: float  # 最后一根日K的 pct_change
    score: int  # 共振分 -4..4
    signal: str  # signal_level 文本
    macd: int  # -1/0/1
    kdj: int
    wr: int
    rsi: int
