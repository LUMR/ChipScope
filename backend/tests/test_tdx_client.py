from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import pytest

from app.services.collector.tdx_client import TdxClient


def _fake_df():
    data = {
        "price": [10.5], "open": [10.2], "last_close": [10.3],
        "high": [10.6], "low": [10.1], "vol": [1000.0], "amount": [1050000.0],
    }
    for i in range(1, 6):
        data[f"bid{i}"] = [10.4 - i * 0.01]
        data[f"bid_vol{i}"] = [100.0 * i]
        data[f"ask{i}"] = [10.6 + i * 0.01]
        data[f"ask_vol{i}"] = [200.0 * i]
    return pd.DataFrame(data)


class _FakeMootdx:
    def quotes(self, symbol):
        return _fake_df()


@pytest.mark.asyncio
async def test_quotes_parses_five_levels():
    client = TdxClient(client=_FakeMootdx(), executor=ThreadPoolExecutor(max_workers=1))
    q = await client.quotes("600519")
    assert q.price == 10.5
    assert q.secucode == "600519"
    assert len(q.bids) == 5 and len(q.asks) == 5
    assert q.bids[0] == (10.39, 100.0)
    assert q.asks[0] == (10.61, 200.0)
    client.close()
