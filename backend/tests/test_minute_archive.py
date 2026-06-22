import pandas as pd
import pytest

from sqlalchemy import select

from app.models.stock import StockMeta
from app.services.minute_archive import _filter_a_shares, refresh_stock_universe
from app.services.collector.types import StockInfo


def test_filter_a_shares_keeps_a_drops_index_bond():
    df = pd.DataFrame(
        {
            "code": ["600519", "999999", "113001", "000001", "300750", "159915"],
            "name": ["贵州茅台", "上证指数", "可转债", "平安银行", "宁德时代", "ETF"],
            "volunit": [100] * 6,
            "decimal_point": [2] * 6,
            "pre_close": [0.0] * 6,
        }
    )
    sh = _filter_a_shares(df, market=1)
    assert {s.code for s in sh} == {"600519"}
    sz = _filter_a_shares(df, market=0)
    assert {s.code for s in sz} == {"000001", "300750"}


def test_filter_a_shares_empty():
    assert _filter_a_shares(None, market=1) == []
    assert _filter_a_shares(pd.DataFrame(), market=0) == []


class _FakeTdx:
    """fake TdxClient：stocks 返回预设 DataFrame。"""

    def __init__(self, sh_df, sz_df):
        self._sh = sh_df
        self._sz = sz_df
        self.calls = []

    async def stocks(self, market: int):
        self.calls.append(market)
        return self._sh if market == 1 else self._sz


@pytest.mark.asyncio
async def test_refresh_stock_universe_upserts_a_shares(db_session):
    from app.database import SessionLocal

    sh_df = pd.DataFrame(
        {"code": ["600519", "999999"], "name": ["贵州茅台", "上证指数"],
         "volunit": [100, 100], "decimal_point": [2, 2], "pre_close": [0.0, 0.0]}
    )
    sz_df = pd.DataFrame(
        {"code": ["000001", "159915"], "name": ["平安银行", "ETF"],
         "volunit": [100, 100], "decimal_point": [2, 2], "pre_close": [0.0, 0.0]}
    )
    codes = await refresh_stock_universe(SessionLocal, _FakeTdx(sh_df, sz_df))
    assert set(codes) == {"600519.SH", "000001.SZ"}
    rows = (await db_session.execute(
        select(StockMeta.code).order_by(StockMeta.code)
    )).scalars().all()
    assert rows == ["000001", "600519"]
