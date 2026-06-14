import asyncio
import time

import httpx

from app.config import get_settings
from app.services.collector.types import KlineBar, StockInfo

_LIST_URL = "https://push2.eastmoney.com/api/qt/clist/get"
_KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"

# 东财 fs：沪深主板/创业板/科创板（北交所 m:0 t:81 留待后续）
_A_SHARE_FS = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"


def _market_of(f13: int) -> str:
    # f13: 1=沪, 0=深
    return "SH" if f13 == 1 else "SZ"


def _secid_of(f13: int, code: str) -> str:
    return f"{f13}.{code}"


def _secucode_of(f13: int, code: str) -> str:
    return f"{code}.{_market_of(f13)}"


class EastMoneyClient:
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        settings = get_settings()
        headers = {
            "User-Agent": settings.eastmoney_user_agent,
            "Referer": "https://quote.eastmoney.com/",
        }
        self._client = client or httpx.AsyncClient(headers=headers, timeout=10.0)
        self._min_interval = settings.eastmoney_min_interval
        self._last_call = 0.0

    async def __aenter__(self) -> "EastMoneyClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()

    async def _throttle(self) -> None:
        now = time.monotonic()
        wait = self._min_interval - (now - self._last_call)
        if wait > 0:
            await asyncio.sleep(wait)
        self._last_call = time.monotonic()

    async def list_stocks(self) -> list[StockInfo]:
        await self._throttle()
        params = {
            "pn": 1,
            "pz": 10000,
            "po": 1,
            "np": 1,
            "fltt": 2,
            "invt": 2,
            "fid": "f3",
            "fs": _A_SHARE_FS,
            "fields": "f12,f13,f14",
        }
        resp = await self._client.get(_LIST_URL, params=params)
        resp.raise_for_status()
        rows = (resp.json().get("data") or {}).get("list") or []
        result = []
        for r in rows:
            f13 = int(r["f13"])
            code = str(r["f12"])
            result.append(
                StockInfo(
                    secucode=_secucode_of(f13, code),
                    code=code,
                    name=str(r["f14"]),
                    market=_market_of(f13),
                    secid=_secid_of(f13, code),
                )
            )
        return result

    async def fetch_daily_kline(
        self, secid: str, beg: str, end: str
    ) -> list[KlineBar]:
        """拉取前复权日K。secid 形如 '1.600519'，beg/end 形如 '20200101'。"""
        await self._throttle()
        params = {
            "secid": secid,
            "klt": "101",  # 日K
            "fqt": "1",  # 前复权
            "beg": beg,
            "end": end,
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        }
        resp = await self._client.get(_KLINE_URL, params=params)
        resp.raise_for_status()
        klines = (resp.json().get("data") or {}).get("klines") or []
        bars = []
        for line in klines:
            parts = line.split(",")
            # f51..f61: 日期,开,收,高,低,量,额,振幅,涨跌幅,涨跌额,换手率
            open_, close, high, low = (
                float(parts[1]),
                float(parts[2]),
                float(parts[3]),
                float(parts[4]),
            )
            vol = int(float(parts[5]))
            amount = float(parts[6])
            pct = float(parts[8]) if parts[8] else 0.0
            turnover = float(parts[10]) if parts[10] else 0.0
            vwap = round(amount / (vol * 100), 3) if vol > 0 else 0.0
            bars.append(
                KlineBar(
                    date=parts[0],
                    open=open_,
                    close=close,
                    high=high,
                    low=low,
                    volume=vol,
                    amount=amount,
                    pct_change=pct,
                    turnover_rate=turnover,
                    vwap=vwap,
                )
            )
        return bars

    async def aclose(self) -> None:
        await self._client.aclose()
