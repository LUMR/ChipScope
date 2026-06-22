# 单日全市场分时概览页 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把原「行情」tab 改名「自选行情」，新增「行情」tab（`/market`）展示某交易日全市场分时聚合概览（平均涨跌幅曲线 + 五档涨跌家数），支持点时刻→榜单→个股分时的两级钻取。

**Architecture:** 后端在分时存档时顺带存全市场昨收（mootdx `stocks().pre_close`）；新增 `services/market_minute.py`（NumPy 聚合纯函数 + DB 读取 + 进程内缓存）与 `api/market.py`（4 接口）。前端新增 `MarketMinutePage` + ECharts 双 grid 图 + 榜单 Modal + 个股抽屉。

**Tech Stack:** FastAPI · SQLAlchemy 2.0 async · NumPy · PostgreSQL JSONB · React 19 · echarts-for-react · Ant Design

## Global Constraints

- Python 全 async；后端命令统一用 `backend/.venv/Scripts/python.exe -m ...`（alembic/pytest 不在 PATH）。
- 测试连独立库 `chipscope_test`（`conftest.py` 顶部 setdefault 强制），每用例 TRUNCATE 隔离；**不 mock DB**，只 mock 外部 HTTP/TCP。
- migration revision id 为纯数字字符串；本计划新增 `0007`，`down_revision="0006"`。
- `secucode` 形如 `600519.SH`；裸 `code` 形如 `600519`。
- 前端 API 走 `api/client.ts` 的 `apiGet<T>(path, params?)`，`params` 自动拼 query。
- ECharts 用 `echarts-for-react` 的 `ReactECharts option={...}`。
- Git commit：中文 conventional 前缀，**不得**带 Co-authored-by / Claude 签名。

---

## Task 1: minute_quote 表加 pre_close 列（model + migration 0007）

**Files:**
- Modify: `backend/app/models/minute_quote.py`
- Create: `backend/alembic/versions/0007_minute_pre_close.py`
- Test: `backend/tests/test_minute_quote_model.py`

**Interfaces:**
- Produces: `MinuteQuote.pre_close: Decimal | None`（后续 Task 2 写入、Task 4 读取）

- [ ] **Step 1: 改 model，先让现有模型测试因新字段暴露**

修改 `backend/app/models/minute_quote.py`，在 `data` 字段后加 `pre_close`：

```python
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Index, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class MinuteQuote(Base):
    __tablename__ = "minute_quote"

    __table_args__ = (
        Index("ix_minute_quote_secucode", "secucode"),
    )

    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    secucode: Mapped[str] = mapped_column(
        String(12), ForeignKey("stock_meta.secucode"), primary_key=True
    )
    data: Mapped[list] = mapped_column(JSONB)  # [{"t":"09:31","price":..,"vol":..}, ...]
    pre_close: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
```

- [ ] **Step 2: 写失败测试（验证 pre_close 可写可读）**

在 `backend/tests/test_minute_quote_model.py` 现有 `test_minute_quote_insert_and_select` 内追加 `pre_close` 的构造与断言（替换整个测试函数）：

```python
@pytest.mark.asyncio
async def test_minute_quote_insert_and_select(db_session):
    from decimal import Decimal

    db_session.add(StockMeta(secucode="600519.SH", code="600519", name="贵州茅台",
                             market="SH", secid="1.600519"))
    await db_session.commit()

    db_session.add(MinuteQuote(
        trade_date=date(2026, 6, 22),
        secucode="600519.SH",
        data=[{"t": "09:31", "price": 1210.31, "vol": 1692}],
        pre_close=Decimal("1685.000"),
    ))
    await db_session.commit()

    row = (
        await db_session.execute(
            select(MinuteQuote).where(
                MinuteQuote.secucode == "600519.SH",
                MinuteQuote.trade_date == date(2026, 6, 22),
            )
        )
    ).scalar_one()
    assert row.data == [{"t": "09:31", "price": 1210.31, "vol": 1692}]
    assert row.pre_close == Decimal("1685.000")
```

- [ ] **Step 3: 跑测试确认通过（测试库靠 `Base.metadata.create_all` 自动建出新列）**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_minute_quote_model.py -v`
Expected: 1 passed

- [ ] **Step 4: 写 migration 0007（开发/生产库用）**

创建 `backend/alembic/versions/0007_minute_pre_close.py`：

```python
"""add pre_close to minute_quote

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-22
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("minute_quote", sa.Column("pre_close", sa.Numeric(12, 3), nullable=True))


def downgrade() -> None:
    op.drop_column("minute_quote", "pre_close")
```

- [ ] **Step 5: 应用 migration 到开发库验证**

Run: `cd backend && .venv/Scripts/alembic upgrade head`
Expected: `Running upgrade 0006 -> 0007, add pre_close to minute_quote`

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/minute_quote.py backend/alembic/versions/0007_minute_pre_close.py backend/tests/test_minute_quote_model.py
git commit -m "feat(market-minute): minute_quote 加 pre_close 列 (migration 0007)"
```

---

## Task 2: StockInfo + 存档流程透传 pre_close

**Files:**
- Modify: `backend/app/services/collector/types.py`
- Modify: `backend/app/services/minute_archive.py`
- Test: `backend/tests/test_minute_archive.py`

**Interfaces:**
- Consumes: `MinuteQuote.pre_close`（Task 1）
- Produces: `StockInfo.pre_close: float | None`；`refresh_stock_universe(...) -> list[StockInfo]`（原返回 `list[str]`）；`upsert_minute_quote(..., pre_close=None)`

- [ ] **Step 1: 给 StockInfo 加 pre_close 字段**

修改 `backend/app/services/collector/types.py` 的 `StockInfo`：

```python
@dataclass(frozen=True)
class StockInfo:
    secucode: str  # 600519.SH
    code: str  # 600519
    name: str
    market: str  # SH / SZ / BJ
    secid: str  # 1.600519
    pre_close: float | None = None  # 昨收，来自 mootdx stocks().pre_close
```

- [ ] **Step 2: 写失败测试 —— `_filter_a_shares` 提取 pre_close**

在 `backend/tests/test_minute_archive.py` 的 `test_filter_a_shares_keeps_a_drops_index_bond` 里把 `pre_close` 改成非零并加断言（替换该测试）：

```python
def test_filter_a_shares_keeps_a_drops_index_bond():
    df = pd.DataFrame(
        {
            "code": ["600519", "999999", "113001", "000001", "300750", "159915"],
            "name": ["贵州茅台", "上证指数", "可转债", "平安银行", "宁德时代", "ETF"],
            "volunit": [100] * 6,
            "decimal_point": [2] * 6,
            "pre_close": [1685.0, 4090.0, 0.0, 12.3, 210.5, 1.5],
        }
    )
    sh = _filter_a_shares(df, market=1)
    assert {s.code for s in sh} == {"600519"}
    assert sh[0].pre_close == 1685.0
    sz = _filter_a_shares(df, market=0)
    assert {s.code for s in sz} == {"000001", "300750"}
    assert {s.code: s.pre_close for s in sz} == {"000001": 12.3, "300750": 210.5}
```

- [ ] **Step 3: 跑测试确认失败**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_minute_archive.py::test_filter_a_shares_keeps_a_drops_index_bond -v`
Expected: FAIL（`StockInfo` 无 pre_close 或字段缺失）

- [ ] **Step 4: 实现 `_filter_a_shares` 提取 pre_close**

修改 `backend/app/services/minute_archive.py` 的 `_filter_a_shares`，在 `out.append(StockInfo(...))` 处加 `pre_close`：

```python
def _filter_a_shares(df, market: int) -> list[StockInfo]:
    if df is None or len(df) == 0:
        return []
    prefixes = _SH_PREFIXES if market == 1 else _SZ_PREFIXES
    suffix = "SH" if market == 1 else "SZ"
    secid_pfx = "1" if market == 1 else "0"
    out: list[StockInfo] = []
    for _, row in df.iterrows():
        code = str(row["code"]).zfill(6)
        if code[:3] in prefixes:
            name = str(row.get("name", code)).replace("\x00", "").strip() or code
            raw_pc = row.get("pre_close", None)
            pre_close = float(raw_pc) if raw_pc not in (None, "") else None
            out.append(StockInfo(
                secucode=f"{code}.{suffix}",
                code=code,
                name=name,
                market=suffix,
                secid=f"{secid_pfx}.{code}",
                pre_close=pre_close,
            ))
    return out
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_minute_archive.py -k filter -v`
Expected: PASS（含 null bytes 测试也应仍通过）

- [ ] **Step 6: 改 `upsert_minute_quote` 接收并写入 pre_close；`refresh_stock_universe` 返回 StockInfo 列表；`archive_minute_quotes` 透传**

修改 `backend/app/services/minute_archive.py`：

```python
async def upsert_minute_quote(
    session: AsyncSession, trade_date: date, secucode: str, points: list[dict],
    pre_close: float | None = None,
) -> int:
    """幂等 upsert 单只分时：ON CONFLICT (trade_date, secucode) DO UPDATE data+pre_close。"""
    if not points:
        return 0
    row = {"trade_date": trade_date, "secucode": secucode, "data": points,
           "pre_close": pre_close}
    stmt = insert(MinuteQuote).values([row])
    stmt = stmt.on_conflict_do_update(
        index_elements=[MinuteQuote.trade_date, MinuteQuote.secucode],
        set_={"data": stmt.excluded.data, "pre_close": stmt.excluded.pre_close,
              "updated_at": func.now()},
    )
    await session.execute(stmt)
    await session.commit()
    return 1


async def refresh_stock_universe(
    session_factory: async_sessionmaker[AsyncSession], tdx: TdxClient
) -> list[StockInfo]:
    """拉沪深全市场清单 → 过滤 A 股 → upsert stock_meta。返回带 pre_close 的 StockInfo 列表。"""
    df_sh = await tdx.stocks(1)
    df_sz = await tdx.stocks(0)
    a_shares = _filter_a_shares(df_sh, 1) + _filter_a_shares(df_sz, 0)
    async with session_factory() as session:
        await upsert_stock_meta(session, a_shares)
    return a_shares
```

并把 `archive_minute_quotes` 主循环改为遍历 `StockInfo`：

```python
    stocks = await refresh_stock_universe(session_factory, tdx)
    total = len(stocks)
    ok = 0
    failed = 0
    today = _today_cst()
    date_arg = None if trade_date == today else trade_date.strftime("%Y%m%d")
    for i, s in enumerate(stocks, 1):
        try:
            points = await tdx.minute_time(s.code, date_arg)
            if points:
                async with session_factory() as session:
                    await upsert_minute_quote(
                        session, trade_date, s.secucode, points, s.pre_close
                    )
                ok += 1
            else:
                failed += 1
        except Exception as e:  # 单只失败不影响其他
            print(f"[archive] {s.secucode} error: {e}")
            failed += 1
        if on_progress is not None:
            on_progress(i, total, failed)
```

- [ ] **Step 7: 更新受影响的现有测试**

在 `backend/tests/test_minute_archive.py`：

(a) `test_refresh_stock_universe_upserts_a_shares`：`refresh_stock_universe` 现返回 `list[StockInfo]`，把 `df` 的 `pre_close` 改非零并改断言：

```python
@pytest.mark.asyncio
async def test_refresh_stock_universe_upserts_a_shares(db_session):
    from app.database import SessionLocal

    sh_df = pd.DataFrame(
        {"code": ["600519", "999999"], "name": ["贵州茅台", "上证指数"],
         "volunit": [100, 100], "decimal_point": [2, 2], "pre_close": [1685.0, 4090.0]}
    )
    sz_df = pd.DataFrame(
        {"code": ["000001", "159915"], "name": ["平安银行", "ETF"],
         "volunit": [100, 100], "decimal_point": [2, 2], "pre_close": [12.3, 1.5]}
    )
    stocks = await refresh_stock_universe(SessionLocal, _FakeTdx(sh_df, sz_df))
    assert {s.secucode for s in stocks} == {"600519.SH", "000001.SZ"}
    assert {s.secucode: s.pre_close for s in stocks} == {"600519.SH": 1685.0, "000001.SZ": 12.3}
    rows = (await db_session.execute(
        select(StockMeta.code).order_by(StockMeta.code)
    )).scalars().all()
    assert rows == ["000001", "600519"]
```

(b) `test_upsert_minute_quote_insert_and_idempotent`：加 `pre_close` 参数与断言：

```python
@pytest.mark.asyncio
async def test_upsert_minute_quote_insert_and_idempotent(db_session):
    from datetime import date
    from app.models.minute_quote import MinuteQuote
    from app.services.minute_archive import upsert_minute_quote

    db_session.add(StockMeta(secucode="600519.SH", code="600519", name="贵州茅台",
                             market="SH", secid="1.600519"))
    await db_session.commit()

    pts = [{"t": "09:31", "price": 10.0, "vol": 100}]
    n1 = await upsert_minute_quote(db_session, date(2026, 6, 22), "600519.SH", pts, pre_close=1685.0)
    assert n1 == 1

    pts2 = [{"t": "09:31", "price": 11.0, "vol": 200}]
    n2 = await upsert_minute_quote(db_session, date(2026, 6, 22), "600519.SH", pts2, pre_close=1685.0)
    assert n2 == 1

    row = (await db_session.execute(
        select(MinuteQuote).where(MinuteQuote.secucode == "600519.SH")
    )).scalar_one()
    assert row.data == pts2
    assert float(row.pre_close) == 1685.0
```

(c) `test_archive_minute_quotes_main_flow`：`_FakeArchiveTdx.stocks` 的 `pre_close` 改非零，并在末尾加 pre_close 落库断言。把两个 `stocks` 返回的 `pre_close` 改为 `[1685.0]` 与 `[12.3, 210.5]`，并在文件末尾 `await _engine.dispose()` 前加：

```python
    # pre_close 随分时落库
    pq_rows = (await db_session.execute(
        select(MinuteQuote.secucode, MinuteQuote.pre_close).order_by(MinuteQuote.secucode)
    )).all()
    assert {r[0]: float(r[1]) for r in pq_rows} == {"000001.SZ": 12.3, "600519.SH": 1685.0}
```

- [ ] **Step 8: 跑全量存档测试**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_minute_archive.py -v`
Expected: 5 passed

- [ ] **Step 9: Commit**

```bash
git add backend/app/services/collector/types.py backend/app/services/minute_archive.py backend/tests/test_minute_archive.py
git commit -m "feat(market-minute): 存档分时时透传全市场 pre_close"
```

---

## Task 3: market_minute 聚合纯函数（limit_pct/classify/aggregate/ranking_at/stock_series）

**Files:**
- Create: `backend/app/services/market_minute.py`
- Test: `backend/tests/test_market_minute.py`

**Interfaces:**
- Produces: `limit_pct(code)->float`、`classify(pct, limit)->str`、`aggregate(rows)->dict`、`ranking_at(rows, time_index, n=30)->dict`、`stock_series(points, pre_close)->list[dict]`、`_time_to_index(t)->int|None`。`rows` 元素形如 `{"secucode","code"|"secucode","pre_close","points":[{"t","price","vol"}],"name"}`。

- [ ] **Step 1: 写失败测试 —— 判定函数**

创建 `backend/tests/test_market_minute.py`：

```python
import pytest

from app.services.market_minute import limit_pct, classify


def test_limit_pct_main_vs_gem():
    assert limit_pct("600519") == 10.0
    assert limit_pct("000001") == 10.0
    assert limit_pct("300750") == 20.0
    assert limit_pct("301236") == 20.0
    assert limit_pct("688981") == 20.0


def test_classify_five_buckets():
    assert classify(9.9, 10.0) == "limit_up"      # >= 10-0.3
    assert classify(10.0, 10.0) == "limit_up"
    assert classify(19.8, 20.0) == "limit_up"
    assert classify(-9.9, 10.0) == "limit_down"
    assert classify(5.0, 10.0) == "up"
    assert classify(-5.0, 10.0) == "down"
    assert classify(0.005, 10.0) == "flat"
    assert classify(-0.005, 10.0) == "flat"
```

- [ ] **Step 2: 跑确认失败**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_market_minute.py -k "limit_pct or classify" -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 market_minute.py 的判定 + 时间工具**

创建 `backend/app/services/market_minute.py`：

```python
"""全市场分时聚合：纯函数（NumPy 向量化）。

rows 元素：{"secucode": str, "pre_close": float|None,
           "points": [{"t":"HH:MM","price":float,"vol":int}, ...],
           "name": str, "code" 可选（缺则从 secucode 解析）}
"""
import numpy as np

from app.services.collector.tdx_client import _row_to_time as _index_to_time

_GEM_PREFIXES = {"300", "301", "688", "689"}  # 创业板/科创板 20%


def limit_pct(code: str) -> float:
    """涨跌停幅度（%）。创业板/科创板 20%，主板 10%。ST 暂不识别。"""
    return 20.0 if code[:3] in _GEM_PREFIXES else 10.0


def classify(pct: float, limit: float) -> str:
    """返回 limit_up / up / flat / down / limit_down。"""
    if pct >= limit - 0.3:
        return "limit_up"
    if pct <= -limit + 0.3:
        return "limit_down"
    if abs(pct) < 0.01:
        return "flat"
    return "up" if pct > 0 else "down"


def _code_of(row: dict) -> str:
    return row.get("code") or row["secucode"].split(".")[0]


def _time_to_index(t: str) -> int | None:
    """HH:MM → 0..239（_index_to_time 的逆）；非分时时段返回 None。"""
    hh, mm = t.split(":")
    total = int(hh) * 60 + int(mm)
    if 571 <= total <= 690:        # 09:31..11:30
        return total - 571
    if 781 <= total <= 900:        # 13:01..15:00
        return total - 661
    return None
```

- [ ] **Step 4: 跑判定测试通过**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_market_minute.py -k "limit_pct or classify" -v`
Expected: PASS

- [ ] **Step 5: 写失败测试 —— aggregate**

先把顶部 import 区改为（追加 `aggregate` 与 `_row_to_time`）：

```python
import pytest

from app.services.collector.tdx_client import _row_to_time
from app.services.market_minute import limit_pct, classify, aggregate
```

再追加到 `test_market_minute.py`：

```python
def _row(secucode, pre_close, prices):
    """构造一行：prices[i] 是第 i 个时刻的价；时刻 0=09:31。"""
    return {
        "secucode": secucode,
        "pre_close": pre_close,
        "name": secucode,
        "points": [{"t": _row_to_time(i), "price": p, "vol": 100} for i, p in enumerate(prices)],
    }


def test_aggregate_avg_and_buckets_and_skip_zero_pre_close():
    from app.services.collector.tdx_client import _row_to_time as idx2t
    # A 主板 pre_close=100，全程 +5%（up）；B 创业板 pre_close=100，第 0 时刻 +20%（涨停）；
    # C pre_close=0（应被剔除）；D 主板 pre_close=100，-6%（down）
    rows = [
        _row("600519.SH", 100.0, [105.0, 105.0, 105.0, 105.0]),
        _row("300750.SZ", 100.0, [120.0, 105.0, 105.0, 105.0]),
        _row("000001.SZ", 0.0, [105.0, 105.0, 105.0, 105.0]),     # 剔除
        _row("601318.SH", 100.0, [94.0, 94.0, 94.0, 94.0]),
    ]
    out = aggregate(rows)
    assert out["summary"]["with_pre_close"] == 3
    assert out["summary"]["total"] == 4
    # 时刻 0：A+5 / B+20涨停 / D-6 → avg=(5+20-6)/3≈6.33
    p0 = out["series"][0]
    assert round(p0["avg_pct"], 2) == 6.33
    assert p0["limit_up"] == 1   # B
    assert p0["up"] == 1         # A
    assert p0["down"] == 1       # D
    assert p0["flat"] == 0
    assert p0["limit_down"] == 0
    # 时刻 1：A+5 / B+5 / D-6 → 涨停 0
    p1 = out["series"][1]
    assert p1["limit_up"] == 0
    assert p1["up"] == 2 and p1["down"] == 1


def test_aggregate_empty_rows():
    out = aggregate([])
    assert out["series"] == []
    assert out["summary"]["total"] == 0 and out["summary"]["with_pre_close"] == 0
```

- [ ] **Step 6: 跑确认失败**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_market_minute.py -k aggregate -v`
Expected: FAIL（aggregate 未定义）

- [ ] **Step 7: 实现 aggregate**

追加到 `market_minute.py`：

```python
_N_POINTS = 240


def aggregate(rows: list[dict]) -> dict:
    """聚合全市场一日 → {series:[...240], summary:{...}}。pre_close<=0 剔除。"""
    pct_rows, limits = [], []
    for r in rows:
        pc = r.get("pre_close")
        if not pc or pc <= 0:
            continue
        code = _code_of(r)
        arr = np.full(_N_POINTS, np.nan)
        for p in r.get("points") or []:
            i = _time_to_index(p["t"])
            if i is not None:
                arr[i] = (float(p["price"]) / float(pc) - 1) * 100
        pct_rows.append(arr)
        limits.append(limit_pct(code))

    total = len(rows)
    with_pc = len(pct_rows)
    if not pct_rows:
        return {"series": [], "summary": {
            "total": total, "with_pre_close": 0,
            "up": 0, "limit_up": 0, "flat": 0, "down": 0, "limit_down": 0,
        }}

    mat = np.vstack(pct_rows)                  # (K, 240)
    lim = np.array(limits)[:, None]            # (K, 1)
    valid = ~np.isnan(mat)
    is_limit_up = (mat >= lim - 0.3) & valid
    is_limit_down = (mat <= -lim + 0.3) & valid
    is_flat = (np.abs(mat) < 0.01) & valid
    is_up = (mat > 0) & ~is_limit_up & valid
    is_down = (mat < 0) & ~is_limit_down & valid

    with np.errstate(all="ignore"):
        avg = np.nanmean(mat, axis=0)          # (240,)

    series = []
    for t in range(_N_POINTS):
        series.append({
            "t": _index_to_time(t),
            "avg_pct": None if np.isnan(avg[t]) else round(float(avg[t]), 4),
            "up": int(is_up[:, t].sum()),
            "limit_up": int(is_limit_up[:, t].sum()),
            "flat": int(is_flat[:, t].sum()),
            "down": int(is_down[:, t].sum()),
            "limit_down": int(is_limit_down[:, t].sum()),
        })
    last = series[_N_POINTS - 1]
    summary = {
        "total": total, "with_pre_close": with_pc,
        "up": last["up"], "limit_up": last["limit_up"], "flat": last["flat"],
        "down": last["down"], "limit_down": last["limit_down"],
    }
    return {"series": series, "summary": summary}
```

- [ ] **Step 8: 跑 aggregate 测试通过**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_market_minute.py -k aggregate -v`
Expected: PASS

- [ ] **Step 9: 写失败测试 —— ranking_at / stock_series**

先把顶部 import 补全为：

```python
from app.services.market_minute import limit_pct, classify, aggregate, ranking_at, stock_series
```

再追加到 `test_market_minute.py`：

```python
def test_ranking_at_top_n_gainers_losers():
    rows = [
        _row("600519.SH", 100.0, [110.0]),   # +10 涨停
        _row("000001.SZ", 100.0, [105.0]),   # +5
        _row("300750.SZ", 100.0, [94.0]),    # -6
        _row("601318.SH", 100.0, [90.0]),    # -10 跌停
    ]
    out = ranking_at(rows, time_index=0, n=2)
    assert out["time"] == "09:31"
    assert [g["secucode"] for g in out["gainers"]] == ["600519.SH", "000001.SZ"]
    assert [l["secucode"] for l in out["losers"]] == ["601318.SH", "300750.SZ"]
    assert out["gainers"][0]["pct"] == 10.0


def test_ranking_at_skips_missing_pre_close():
    rows = [_row("600519.SH", 0.0, [110.0]), _row("000001.SZ", 100.0, [105.0])]
    out = ranking_at(rows, time_index=0)
    assert len(out["gainers"]) == 1 and out["gainers"][0]["secucode"] == "000001.SZ"


def test_stock_series_with_and_without_pre_close():
    pts = [{"t": "09:31", "price": 105.0, "vol": 100}, {"t": "09:32", "price": 110.0, "vol": 200}]
    s1 = stock_series(pts, 100.0)
    assert s1 == [{"t": "09:31", "price": 105.0, "vol": 100, "pct": 5.0},
                  {"t": "09:32", "price": 110.0, "vol": 200, "pct": 10.0}]
    s2 = stock_series(pts, None)
    assert s2[0]["pct"] is None
```

- [ ] **Step 10: 跑确认失败**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_market_minute.py -k "ranking_at or stock_series" -v`
Expected: FAIL

- [ ] **Step 11: 实现 ranking_at / stock_series**

追加到 `market_minute.py`：

```python
def ranking_at(rows: list[dict], time_index: int, n: int = 30) -> dict:
    """某时刻全市场按 pct 排序，返回 {time, gainers, losers} 各 top n。"""
    items = []
    for r in rows:
        pc = r.get("pre_close")
        pts = r.get("points") or []
        if not pc or pc <= 0 or time_index >= len(pts):
            continue
        price = float(pts[time_index]["price"])
        pct = (price / float(pc) - 1) * 100
        items.append({
            "secucode": r["secucode"], "name": r.get("name") or r["secucode"],
            "price": round(price, 3), "pct": round(pct, 3),
        })
    items.sort(key=lambda x: x["pct"], reverse=True)
    return {
        "time": _index_to_time(time_index),
        "gainers": items[:n],
        "losers": list(reversed(items[-n:])) if items else [],
    }


def stock_series(points: list[dict], pre_close) -> list[dict]:
    """单股分时加涨跌幅：[{t, price, vol, pct}]。pre_close<=0 时 pct=None。"""
    out = []
    for p in points:
        pct = None
        if pre_close and float(pre_close) > 0:
            pct = round((float(p["price"]) / float(pre_close) - 1) * 100, 3)
        out.append({"t": p["t"], "price": float(p["price"]), "vol": int(p["vol"]), "pct": pct})
    return out
```

- [ ] **Step 12: 跑 market_minute 全部测试**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_market_minute.py -v`
Expected: PASS（全部）

- [ ] **Step 13: Commit**

```bash
git add backend/app/services/market_minute.py backend/tests/test_market_minute.py
git commit -m "feat(market-minute): 聚合/钻取纯函数 (limit_pct/classify/aggregate/ranking_at/stock_series)"
```

---

## Task 4: DB 读取 + 缓存 + 响应 schema

**Files:**
- Create: `backend/app/schemas/market.py`
- Modify: `backend/app/services/market_minute.py`（追加 async DB 层）
- Test: `backend/tests/test_market_minute.py`（追加 DB 测试）

**Interfaces:**
- Consumes: Task 1 `MinuteQuote.pre_close`；Task 3 纯函数
- Produces: `load_day(session, trade_date)`、`get_overview(session, trade_date)`、`get_ranking(session, trade_date, time_str)`、`get_stock(session, trade_date, secucode)`、`list_dates(session)`；schema 类 `OverviewOut` 等

- [ ] **Step 1: 写响应 schema**

创建 `backend/app/schemas/market.py`：

```python
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
```

- [ ] **Step 2: 追加 DB 层到 market_minute.py**

在 `backend/app/services/market_minute.py` 末尾追加：

```python
from datetime import date  # noqa: E402

from sqlalchemy import distinct, select  # noqa: E402

from app.models.minute_quote import MinuteQuote  # noqa: E402
from app.models.stock import StockMeta  # noqa: E402

_rows_cache: dict[date, list[dict]] = {}
_overview_cache: dict[date, dict] = {}


def reset_caches() -> None:
    """测试用：清空进程内缓存。"""
    _rows_cache.clear()
    _overview_cache.clear()


async def load_day(session, trade_date: date) -> list[dict]:
    """读当日全市场 minute_quote(data, pre_close) join stock_meta(name)。"""
    stmt = (
        select(MinuteQuote, StockMeta.name)
        .join(StockMeta, MinuteQuote.secucode == StockMeta.secucode)
        .where(MinuteQuote.trade_date == trade_date)
    )
    result = await session.execute(stmt)
    return [
        {
            "secucode": mq.secucode,
            "pre_close": float(mq.pre_close) if mq.pre_close is not None else None,
            "points": mq.data or [],
            "name": name,
        }
        for mq, name in result
    ]


async def get_overview(session, trade_date: date) -> dict:
    if trade_date not in _overview_cache:
        rows = await load_day(session, trade_date)
        _rows_cache[trade_date] = rows
        _overview_cache[trade_date] = aggregate(rows)
    return _overview_cache[trade_date]


async def get_ranking(session, trade_date: date, time_str: str) -> dict:
    idx = _time_to_index(time_str)
    if idx is None:
        raise ValueError("invalid time")
    rows = _rows_cache.get(trade_date) or await load_day(session, trade_date)
    _rows_cache[trade_date] = rows
    return ranking_at(rows, idx)


async def get_stock(session, trade_date: date, secucode: str) -> dict | None:
    stmt = (
        select(MinuteQuote, StockMeta.name)
        .join(StockMeta, MinuteQuote.secucode == StockMeta.secucode)
        .where(MinuteQuote.trade_date == trade_date, MinuteQuote.secucode == secucode)
    )
    row = (await session.execute(stmt)).first()
    if row is None:
        return None
    mq, name = row
    pc = float(mq.pre_close) if mq.pre_close is not None else None
    return {
        "secucode": mq.secucode, "name": name, "pre_close": pc,
        "points": stock_series(mq.data or [], pc),
    }


async def list_dates(session) -> list[str]:
    stmt = select(distinct(MinuteQuote.trade_date)).order_by(MinuteQuote.trade_date.desc())
    result = await session.execute(stmt)
    return [d.isoformat() for d in result.scalars().all()]
```

- [ ] **Step 3: 写 DB 层失败测试**

追加到 `test_market_minute.py`：

```python
@pytest.mark.asyncio
async def test_get_overview_reads_db_and_caches(db_session):
    from datetime import date
    from app.models.minute_quote import MinuteQuote
    from app.models.stock import StockMeta
    from app.services import market_minute as mm

    mm.reset_caches()
    db_session.add(StockMeta(secucode="600519.SH", code="600519", name="贵州茅台",
                             market="SH", secid="1.600519"))
    db_session.add(StockMeta(secucode="000001.SZ", code="000001", name="平安银行",
                             market="SZ", secid="0.000001"))
    await db_session.commit()
    db_session.add(MinuteQuote(trade_date=date(2026, 6, 22), secucode="600519.SH",
                               data=[{"t": "09:31", "price": 105.0, "vol": 100}], pre_close=100))
    db_session.add(MinuteQuote(trade_date=date(2026, 6, 22), secucode="000001.SZ",
                               data=[{"t": "09:31", "price": 94.0, "vol": 100}], pre_close=100))
    await db_session.commit()

    out = await mm.get_overview(db_session, date(2026, 6, 22))
    assert out["summary"]["with_pre_close"] == 2
    assert out["series"][0]["up"] == 1 and out["series"][0]["down"] == 1
    # 命中缓存：date(2026,6,22) in _overview_cache
    assert date(2026, 6, 22) in mm._overview_cache


@pytest.mark.asyncio
async def test_get_ranking_and_stock_and_dates(db_session):
    from datetime import date
    from app.models.minute_quote import MinuteQuote
    from app.models.stock import StockMeta
    from app.services import market_minute as mm

    mm.reset_caches()
    db_session.add(StockMeta(secucode="600519.SH", code="600519", name="贵州茅台",
                             market="SH", secid="1.600519"))
    await db_session.commit()
    db_session.add(MinuteQuote(trade_date=date(2026, 6, 18), secucode="600519.SH",
                               data=[{"t": "09:31", "price": 110.0, "vol": 5}], pre_close=100))
    await db_session.commit()

    rk = await mm.get_ranking(db_session, date(2026, 6, 18), "09:31")
    assert rk["gainers"][0]["secucode"] == "600519.SH"

    st = await mm.get_stock(db_session, date(2026, 6, 18), "600519.SH")
    assert st["points"][0]["pct"] == 10.0 and st["pre_close"] == 100.0
    assert await mm.get_stock(db_session, date(2026, 6, 18), "999999.SZ") is None

    dates = await mm.list_dates(db_session)
    assert dates == ["2026-06-18"]
```

- [ ] **Step 4: 跑 DB 层测试**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_market_minute.py -v`
Expected: PASS（含新 DB 测试）

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/market.py backend/app/services/market_minute.py backend/tests/test_market_minute.py
git commit -m "feat(market-minute): DB 读取层 + 进程内缓存 + 响应 schema"
```

---

## Task 5: api/market.py 四接口 + main 注册

**Files:**
- Create: `backend/app/api/market.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_api_market.py`

**Interfaces:**
- Consumes: Task 4 的 `list_dates/get_overview/get_ranking/get_stock` + schema
- Produces: `router`（prefix `/api/market/minute`），端点 `GET /dates`、`/overview`、`/ranking`、`/stock`

- [ ] **Step 1: 写接口测试**

创建 `backend/tests/test_api_market.py`：

```python
from datetime import date

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models.minute_quote import MinuteQuote
from app.models.stock import StockMeta
from app.services import market_minute as mm


@pytest.fixture(autouse=True)
def _clean_cache():
    mm.reset_caches()
    yield
    mm.reset_caches()


@pytest.mark.asyncio
async def test_overview_ranking_stock_dates(db_session):
    db_session.add(StockMeta(secucode="600519.SH", code="600519", name="贵州茅台",
                             market="SH", secid="1.600519"))
    await db_session.commit()
    db_session.add(MinuteQuote(trade_date=date(2026, 6, 18), secucode="600519.SH",
                               data=[{"t": "09:31", "price": 110.0, "vol": 5}], pre_close=100))
    await db_session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        dates = (await ac.get("/api/market/minute/dates")).json()
        assert dates == ["2026-06-18"]

        ov = (await ac.get("/api/market/minute/overview", params={"date": "2026-06-18"})).json()
        assert ov["trade_date"] == "2026-06-18"
        assert ov["summary"]["with_pre_close"] == 1

        rk = (await ac.get("/api/market/minute/ranking",
                           params={"date": "2026-06-18", "time": "09:31"})).json()
        assert rk["gainers"][0]["secucode"] == "600519.SH"

        st = (await ac.get("/api/market/minute/stock",
                           params={"date": "2026-06-18", "secucode": "600519.SH"})).json()
        assert st["pre_close"] == 100.0 and st["points"][0]["pct"] == 10.0


@pytest.mark.asyncio
async def test_overview_no_data_404(db_session):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.get("/api/market/minute/overview", params={"date": "2020-01-01"})
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_ranking_invalid_time_422(db_session):
    db_session.add(StockMeta(secucode="600519.SH", code="600519", name="贵州茅台",
                             market="SH", secid="1.600519"))
    db_session.add(MinuteQuote(trade_date=date(2026, 6, 18), secucode="600519.SH",
                               data=[{"t": "09:31", "price": 110.0, "vol": 5}], pre_close=100))
    await db_session.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.get("/api/market/minute/ranking",
                         params={"date": "2026-06-18", "time": "08:00"})
        assert r.status_code == 422
```

- [ ] **Step 2: 跑确认失败**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_api_market.py -v`
Expected: FAIL（路由不存在 / 404）

- [ ] **Step 3: 实现接口**

创建 `backend/app/api/market.py`：

```python
"""单日全市场分时概览查询接口。"""
from datetime import date, datetime

from fastapi import APIRouter, HTTPException, Query

from app.database import SessionLocal
from app.schemas.market import (
    OverviewOut, RankItemOut, RankingOut, StockMinuteOut,
)
from app.services import market_minute as mm

router = APIRouter(prefix="/api/market/minute", tags=["market"])


def _parse_date(s: str) -> date:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=422, detail="invalid date, expected YYYY-MM-DD")


@router.get("/dates", response_model=list[str])
async def available_dates():
    async with SessionLocal() as session:
        return await mm.list_dates(session)


@router.get("/overview", response_model=OverviewOut)
async def overview(date: str = Query(...)):
    trade_date = _parse_date(date)
    async with SessionLocal() as session:
        out = await mm.get_overview(session, trade_date)
    if not out["series"]:
        raise HTTPException(status_code=404, detail="no minute data for this date")
    return OverviewOut(trade_date=trade_date.isoformat(), **out)


@router.get("/ranking", response_model=RankingOut)
async def ranking(date: str = Query(...), time: str = Query(...)):
    trade_date = _parse_date(date)
    async with SessionLocal() as session:
        try:
            out = await mm.get_ranking(session, trade_date, time)
        except ValueError:
            raise HTTPException(status_code=422, detail="invalid time, expected HH:MM in 09:31..15:00")
    return RankingOut(**out)


@router.get("/stock", response_model=StockMinuteOut)
async def stock(date: str = Query(...), secucode: str = Query(...)):
    trade_date = _parse_date(date)
    async with SessionLocal() as session:
        out = await mm.get_stock(session, trade_date, secucode)
    if out is None:
        raise HTTPException(status_code=404, detail="no minute data for this stock/date")
    return StockMinuteOut(**out)
```

> 注意：`RankingOut` 字段是 `time/gainers/losers`，`get_ranking` 返回的 dict 键同名，`**out` 展开匹配。`OverviewOut` 多一个 `trade_date` 由接口注入，故 `OverviewOut(trade_date=..., **out)`（`out` 含 `series/summary`）。`RankItemOut`/`StockMinuteOut` 为嵌套模型，FastAPI 自动校验 dict→model。

- [ ] **Step 4: 在 main.py 注册 router**

修改 `backend/app/main.py`：在 import 区加 `from app.api.market import router as market_router`，在 `app.include_router(archive_router)` 后加 `app.include_router(market_router)`。

- [ ] **Step 5: 跑接口测试 + 全量后端测试**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_api_market.py -v`
Expected: PASS

Run: `cd backend && .venv/Scripts/python.exe -m pytest`
Expected: 全绿（含原有用例）

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/market.py backend/app/main.py backend/tests/test_api_market.py
git commit -m "feat(market-minute): 概览/榜单/个股/日期 四个查询接口"
```

---

## Task 6: 前端 api/market.ts + 路由 + 导航改名 + 页面骨架

**Files:**
- Create: `frontend/src/api/market.ts`
- Create: `frontend/src/pages/MarketMinutePage.tsx`（骨架，图表位留占位）
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/TopNav.tsx`

**Interfaces:**
- Produces: `getMarketDates/getMarketOverview/getMarketRanking/getStockMinute` + TS 类型；路由 `/market`；TopNav「自选行情」+「行情」两个 tab

- [ ] **Step 1: 写 api 层**

创建 `frontend/src/api/market.ts`：

```ts
import { apiGet } from "./client";

export interface OverviewPoint {
  t: string;
  avg_pct: number | null;
  up: number;
  limit_up: number;
  flat: number;
  down: number;
  limit_down: number;
}

export interface OverviewSummary {
  total: number;
  with_pre_close: number;
  up: number;
  limit_up: number;
  flat: number;
  down: number;
  limit_down: number;
}

export interface Overview {
  trade_date: string;
  series: OverviewPoint[];
  summary: OverviewSummary;
}

export interface RankItem {
  secucode: string;
  name: string;
  price: number;
  pct: number;
}

export interface Ranking {
  time: string;
  gainers: RankItem[];
  losers: RankItem[];
}

export interface StockMinutePoint {
  t: string;
  price: number;
  vol: number;
  pct: number | null;
}

export interface StockMinute {
  secucode: string;
  name: string;
  pre_close: number | null;
  points: StockMinutePoint[];
}

export const getMarketDates = () => apiGet<string[]>("/market/minute/dates");
export const getMarketOverview = (date: string) =>
  apiGet<Overview>("/market/minute/overview", { date });
export const getMarketRanking = (date: string, time: string) =>
  apiGet<Ranking>("/market/minute/ranking", { date, time });
export const getStockMinute = (date: string, secucode: string) =>
  apiGet<StockMinute>("/market/minute/stock", { date, secucode });
```

- [ ] **Step 2: 写页面骨架（DatePicker + 汇总数字，图表占位）**

创建 `frontend/src/pages/MarketMinutePage.tsx`：

```tsx
import { Card, DatePicker, Empty, message, Space, Spin, Typography } from "antd";
import dayjs, { Dayjs } from "dayjs";
import { useEffect, useState } from "react";
import { getMarketDates, getMarketOverview, type Overview } from "../api/market";

const { Text, Title } = Typography;

export default function MarketMinutePage() {
  const [dates, setDates] = useState<string[]>([]);
  const [date, setDate] = useState<Dayjs | null>(null);
  const [overview, setOverview] = useState<Overview | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    getMarketDates().then((ds) => {
      setDates(ds);
      if (ds.length) setDate(dayjs(ds[0]));
    }).catch(() => message.error("加载可用交易日失败"));
  }, []);

  useEffect(() => {
    if (!date) return;
    setLoading(true);
    getMarketOverview(date.format("YYYY-MM-DD"))
      .then(setOverview)
      .catch((e: any) => {
        const msg = String(e?.message || e);
        if (msg.includes("404")) {
          setOverview(null);
        } else {
          message.error(msg);
        }
      })
      .finally(() => setLoading(false));
  }, [date]);

  const s = overview?.summary;

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <Card>
        <Space>
          <Text strong>交易日</Text>
          <DatePicker
            value={date}
            onChange={(d) => d && setDate(d)}
            disabledDate={(d) => !dates.includes(d.format("YYYY-MM-DD"))}
            allowClear={false}
          />
        </Space>
      </Card>

      {loading && <Spin />}
      {!loading && !overview && <Empty description="该交易日无分时存档" />}

      {overview && s && (
        <>
          <Card title={<Title level={5} style={{ margin: 0 }}>当日汇总（收盘）</Title>}>
            <Space size="large" wrap>
              <Text>参与 <b>{s.with_pre_close}</b>/{s.total}</Text>
              <Text type="danger">涨停 {s.limit_up}</Text>
              <Text type="danger">上涨 {s.up}</Text>
              <Text type="secondary">平盘 {s.flat}</Text>
              <Text type="success">下跌 {s.down}</Text>
              <Text type="success">跌停 {s.limit_down}</Text>
            </Space>
          </Card>
          <Card title="全市场分时走势">
            <div style={{ padding: 24, color: "#9ca3af" }}>
              图表待接入（Task 7）
            </div>
          </Card>
        </>
      )}
    </Space>
  );
}
```

- [ ] **Step 3: 注册路由**

修改 `frontend/src/App.tsx`，加 import 与 Route：

```tsx
import { Navigate, Route, Routes } from "react-router-dom";
import AppLayout from "./components/AppLayout";
import StockDetail from "./pages/StockDetail";
import WatchlistPage from "./pages/WatchlistPage";
import ArchivePage from "./pages/ArchivePage";
import MarketMinutePage from "./pages/MarketMinutePage";

export default function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route path="/" element={<Navigate to="/stock/600519.SH" replace />} />
        <Route path="/stock/:secucode" element={<StockDetail />} />
        <Route path="/watchlist" element={<WatchlistPage />} />
        <Route path="/archive" element={<ArchivePage />} />
        <Route path="/market" element={<MarketMinutePage />} />
      </Route>
    </Routes>
  );
}
```

- [ ] **Step 4: 改 TopNav —— 改名 + 新 tab + activeKey**

修改 `frontend/src/components/TopNav.tsx`：

```tsx
  const activeKey = loc.pathname.startsWith("/watchlist")
    ? "watchlist"
    : loc.pathname.startsWith("/archive")
    ? "archive"
    : loc.pathname.startsWith("/market")
    ? "minute"
    : "market";

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 24, height: "100%" }}>
      <strong style={{ color: "#5b6cff", fontSize: 18 }}>◣ ChipScope</strong>
      <Menu
        mode="horizontal"
        selectedKeys={[activeKey]}
        style={{ flex: 1, borderBottom: "none" }}
        items={[
          { key: "market", label: "自选行情", onClick: () => nav("/") },
          { key: "minute", label: "行情", onClick: () => nav("/market") },
          { key: "watchlist", label: "自选管理", onClick: () => nav("/watchlist") },
          { key: "archive", label: "数据存档", onClick: () => nav("/archive") },
        ]}
      />
```

（其余 AutoComplete 部分保持不变。）

- [ ] **Step 5: 跑前端 lint + build**

Run: `cd frontend && npm run lint && npm run build`
Expected: 无错误

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/market.ts frontend/src/pages/MarketMinutePage.tsx frontend/src/App.tsx frontend/src/components/TopNav.tsx
git commit -m "feat(market-minute): 前端 api 层 + /market 路由 + 导航改名自选行情"
```

---

## Task 7: MarketOverviewChart（ECharts 双 grid + 点击钻取回调）

**Files:**
- Create: `frontend/src/components/MarketOverviewChart.tsx`
- Modify: `frontend/src/pages/MarketMinutePage.tsx`（接入图表，替换占位）
- Test: `frontend/src/components/MarketOverviewChart.test.tsx`

**Interfaces:**
- Consumes: `Overview` 类型（Task 6）；`onPickTime(t: string)` 回调
- Produces: `<MarketOverviewChart overview={...} onPickTime={...} />`

- [ ] **Step 1: 写组件**

创建 `frontend/src/components/MarketOverviewChart.tsx`：

```tsx
import ReactECharts from "echarts-for-react";
import type { Overview } from "../api/market";

const COLORS = {
  limitUp: "#7f1d1d",
  up: "#f5222d",
  flat: "#9ca3af",
  down: "#16a34a",
  limitDown: "#14532d",
};

export default function MarketOverviewChart({
  overview,
  onPickTime,
}: {
  overview: Overview;
  onPickTime: (t: string) => void;
}) {
  const xs = overview.series.map((p) => p.t);
  const avg = overview.series.map((p) => p.avg_pct);
  const mk = (key: keyof typeof COLORS) => overview.series.map((p) => p[key] as number);

  const option = {
    tooltip: { trigger: "axis", axisPointer: { type: "cross" } },
    legend: {
      data: ["平均涨跌幅", "涨停", "上涨", "平盘", "下跌", "跌停"],
      top: 0,
    },
    axisPointer: { link: [{ xAxisIndex: "all" }] },
    grid: [
      { left: 48, right: 24, top: 40, height: "55%" },
      { left: 48, right: 24, top: "72%", height: "22%" },
    ],
    xAxis: [
      { type: "category", data: xs, gridIndex: 0, axisLabel: { show: false } },
      { type: "category", data: xs, gridIndex: 1, axisLabel: { fontSize: 10 } },
    ],
    yAxis: [
      { type: "value", gridIndex: 0, axisLabel: { formatter: "{value}%" } },
      { type: "value", gridIndex: 1 },
    ],
    series: [
      {
        name: "平均涨跌幅", type: "line", xAxisIndex: 0, yAxisIndex: 0,
        data: avg, showSymbol: false, smooth: true,
        lineStyle: { width: 1.6 }, itemStyle: { color: "#5b6cff" },
        markLine: { silent: true, data: [{ yAxis: 0 }], lineStyle: { color: "#475569" } },
      },
      { name: "涨停", type: "bar", stack: "cnt", xAxisIndex: 1, yAxisIndex: 1,
        data: mk("limit_up"), itemStyle: { color: COLORS.limitUp } },
      { name: "上涨", type: "bar", stack: "cnt", xAxisIndex: 1, yAxisIndex: 1,
        data: mk("up"), itemStyle: { color: COLORS.up } },
      { name: "平盘", type: "bar", stack: "cnt", xAxisIndex: 1, yAxisIndex: 1,
        data: mk("flat"), itemStyle: { color: COLORS.flat } },
      { name: "下跌", type: "bar", stack: "cnt", xAxisIndex: 1, yAxisIndex: 1,
        data: mk("down"), itemStyle: { color: COLORS.down } },
      { name: "跌停", type: "bar", stack: "cnt", xAxisIndex: 1, yAxisIndex: 1,
        data: mk("limit_down"), itemStyle: { color: COLORS.limitDown } },
    ],
  };

  return (
    <ReactECharts
      option={option}
      style={{ height: 420 }}
      onEvents={{ click: (params: any) => {
        if (params.componentType === "series" || params.componentType === "line") {
          onPickTime(params.name);
        }
      } }}
    />
  );
}
```

- [ ] **Step 2: 写组件测试**

创建 `frontend/src/components/MarketOverviewChart.test.tsx`（参考 `ChipFlame.test.tsx`：用 `vi.mock` 把 ECharts 替换成捕获 `onEvents` 的桩）：

```tsx
import { it, expect, vi } from "vitest";
import { render } from "@testing-library/react";
import type { Overview } from "../api/market";

const { propsHolder } = vi.hoisted(() => ({ propsHolder: { onEvents: null as unknown } }));

vi.mock("echarts-for-react", () => ({
  default: (props: any) => {
    propsHolder.onEvents = props.onEvents;
    return null;
  },
}));

import MarketOverviewChart from "./MarketOverviewChart";

const ov: Overview = {
  trade_date: "2026-06-18",
  series: [{ t: "10:42", avg_pct: 0.5, up: 1, limit_up: 0, flat: 0, down: 1, limit_down: 0 }],
  summary: { total: 2, with_pre_close: 2, up: 1, limit_up: 0, flat: 0, down: 1, limit_down: 0 },
};

it("registers a click handler that maps a line click to onPickTime", () => {
  let picked = "";
  render(<MarketOverviewChart overview={ov} onPickTime={(t) => (picked = t)} />);
  (propsHolder.onEvents as any).click({ componentType: "line", name: "10:42" });
  expect(picked).toBe("10:42");
});
```

- [ ] **Step 3: 跑组件测试**

Run: `cd frontend && npx vitest run src/components/MarketOverviewChart.test.tsx`
Expected: PASS

- [ ] **Step 4: 接入 MarketMinutePage，替换占位**

修改 `frontend/src/pages/MarketMinutePage.tsx`：加 `import MarketMinuteChart from "../components/MarketOverviewChart";`（注意：占位 div 所在 Card 的内容替换为 `<MarketMinuteChart overview={overview} onPickTime={() => {}} />`）。把「图表待接入」那个 `<div ...>图表待接入（Task 7）</div>` 替换为：

```tsx
            <MarketOverviewChart overview={overview} onPickTime={() => {}} />
```

- [ ] **Step 5: 跑 build**

Run: `cd frontend && npm run build`
Expected: 无错误

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/MarketOverviewChart.tsx frontend/src/components/MarketOverviewChart.test.tsx frontend/src/pages/MarketMinutePage.tsx
git commit -m "feat(market-minute): 分时概览双 grid 图表 + 点击钻取回调"
```

---

## Task 8: MomentRankingModal + StockMinuteDrawer

**Files:**
- Create: `frontend/src/components/MomentRankingModal.tsx`
- Create: `frontend/src/components/StockMinuteDrawer.tsx`
- Test: `frontend/src/components/MomentRankingModal.test.tsx`

**Interfaces:**
- Consumes: `Ranking`、`StockMinute` 类型；`onPickStock(secucode)` 回调
- Produces: `<MomentRankingModal ranking open time onClose onPickStock />`；`<StockMinuteDrawer open data date onClose />`

- [ ] **Step 1: 写榜单 Modal**

创建 `frontend/src/components/MomentRankingModal.tsx`：

```tsx
import { Modal, Table, Tag, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import type { RankItem, Ranking } from "../api/market";

const { Text } = Typography;

const columns = (onPick: (s: string) => void): ColumnsType<RankItem> => [
  { title: "代码", dataIndex: "secucode", render: (v: string) => <a onClick={() => onPick(v)}>{v}</a> },
  { title: "名称", dataIndex: "name" },
  { title: "现价", dataIndex: "price", align: "right", render: (v: number) => v.toFixed(2) },
  {
    title: "涨幅", dataIndex: "pct", align: "right",
    render: (v: number) => {
      const color = v > 0 ? "#f5222d" : v < 0 ? "#16a34a" : "#9ca3af";
      return <span style={{ color }}>{v >= 0 ? "+" : ""}{v.toFixed(2)}%</span>;
    },
  },
];

export default function MomentRankingModal({
  ranking, open, onClose, onPickStock,
}: {
  ranking: Ranking | null;
  open: boolean;
  onClose: () => void;
  onPickStock: (secucode: string) => void;
}) {
  return (
    <Modal
      title={ranking ? `分时榜单 · ${ranking.time}` : "分时榜单"}
      open={open}
      onCancel={onClose}
      footer={null}
      width={640}
    >
      {ranking && (
        <>
          <Text type="danger">涨幅前 {ranking.gainers.length}</Text>
          <Table
            size="small" pagination={false} rowKey="secucode"
            dataSource={ranking.gainers} columns={columns(onPickStock)}
          />
          <Text type="success" style={{ display: "block", marginTop: 12 }}>
            跌幅前 {ranking.losers.length}
          </Text>
          <Table
            size="small" pagination={false} rowKey="secucode"
            dataSource={ranking.losers} columns={columns(onPickStock)}
          />
        </>
      )}
    </Modal>
  );
}
```

- [ ] **Step 2: 写个股抽屉**

创建 `frontend/src/components/StockMinuteDrawer.tsx`：

```tsx
import { Drawer, Empty, Spin, Typography } from "antd";
import ReactECharts from "echarts-for-react";
import type { StockMinute } from "../api/market";

const { Text } = Typography;

export default function StockMinuteDrawer({
  open, data, loading, onClose,
}: {
  open: boolean;
  data: StockMinute | null;
  loading: boolean;
  onClose: () => void;
}) {
  const xs = data?.points.map((p) => p.t) ?? [];
  const prices = data?.points.map((p) => p.price) ?? [];
  const pcts = data?.points.map((p) => p.pct) ?? [];
  const option = {
    tooltip: { trigger: "axis" },
    legend: { data: ["价格", "涨幅%"] },
    xAxis: { type: "category", data: xs, axisLabel: { fontSize: 10 } },
    yAxis: [
      { type: "value", scale: true, name: "价" },
      { type: "value", name: "%" },
    ],
    series: [
      { name: "价格", type: "line", data: prices, showSymbol: false, itemStyle: { color: "#5b6cff" } },
      { name: "涨幅%", type: "line", yAxisIndex: 1, data: pcts, showSymbol: false, itemStyle: { color: "#f5222d" } },
    ],
  };
  return (
    <Drawer
      title={data ? `${data.name} · ${data.secucode}` : "个股分时"}
      open={open} onClose={onClose} width={480}
    >
      {loading && <Spin />}
      {!loading && !data && <Empty description="无分时数据" />}
      {!loading && data && (
        <>
          <Text type="secondary">昨收 {data.pre_close?.toFixed(2) ?? "-"}</Text>
          <ReactECharts option={option} style={{ height: 320, marginTop: 12 }} />
        </>
      )}
    </Drawer>
  );
}
```

- [ ] **Step 3: 写榜单 Modal 测试**

创建 `frontend/src/components/MomentRankingModal.test.tsx`：

```tsx
import { it, expect } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import MomentRankingModal from "./MomentRankingModal";
import type { Ranking } from "../api/market";

const ranking: Ranking = {
  time: "10:42",
  gainers: [{ secucode: "600519.SH", name: "贵州茅台", price: 1685, pct: 5.2 }],
  losers: [{ secucode: "601318.SH", name: "中国平安", price: 45, pct: -3.1 }],
};

it("clicking a row code fires onPickStock", () => {
  let picked = "";
  render(
    <MomentRankingModal ranking={ranking} open onClose={() => {}} onPickStock={(s) => (picked = s)} />,
  );
  fireEvent.click(screen.getByText("600519.SH"));
  expect(picked).toBe("600519.SH");
});
```

- [ ] **Step 4: 跑组件测试**

Run: `cd frontend && npx vitest run src/components/MomentRankingModal.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/MomentRankingModal.tsx frontend/src/components/StockMinuteDrawer.tsx frontend/src/components/MomentRankingModal.test.tsx
git commit -m "feat(market-minute): 分时榜单 Modal + 个股分时抽屉"
```

---

## Task 9: 串接钻取链路 + README + 全量收尾

**Files:**
- Modify: `frontend/src/pages/MarketMinutePage.tsx`（串 chart→modal→drawer）
- Modify: `README.md`

- [ ] **Step 1: 在 MarketMinutePage 串接钻取**

把 `frontend/src/pages/MarketMinutePage.tsx` 改为完整版（替换整个文件）：

```tsx
import { Card, DatePicker, Empty, message, Space, Spin, Typography } from "antd";
import dayjs, { Dayjs } from "dayjs";
import { useEffect, useState } from "react";
import {
  getMarketDates,
  getMarketOverview,
  getMarketRanking,
  getStockMinute,
  type Overview,
  type Ranking,
  type StockMinute,
} from "../api/market";
import MarketOverviewChart from "../components/MarketOverviewChart";
import MomentRankingModal from "../components/MomentRankingModal";
import StockMinuteDrawer from "../components/StockMinuteDrawer";

const { Text, Title } = Typography;

export default function MarketMinutePage() {
  const [dates, setDates] = useState<string[]>([]);
  const [date, setDate] = useState<Dayjs | null>(null);
  const [overview, setOverview] = useState<Overview | null>(null);
  const [loading, setLoading] = useState(false);

  const [ranking, setRanking] = useState<Ranking | null>(null);
  const [rankOpen, setRankOpen] = useState(false);

  const [stock, setStock] = useState<StockMinute | null>(null);
  const [stockOpen, setStockOpen] = useState(false);
  const [stockLoading, setStockLoading] = useState(false);

  useEffect(() => {
    getMarketDates().then((ds) => {
      setDates(ds);
      if (ds.length) setDate(dayjs(ds[0]));
    }).catch(() => message.error("加载可用交易日失败"));
  }, []);

  useEffect(() => {
    if (!date) return;
    setLoading(true);
    setOverview(null);
    getMarketOverview(date.format("YYYY-MM-DD"))
      .then(setOverview)
      .catch((e: any) => {
        if (!String(e?.message || e).includes("404")) message.error(String(e?.message || e));
      })
      .finally(() => setLoading(false));
  }, [date]);

  const pickTime = (t: string) => {
    if (!date) return;
    setRankOpen(true);
    getMarketRanking(date.format("YYYY-MM-DD"), t)
      .then(setRanking)
      .catch((e: any) => message.error(String(e?.message || e)));
  };

  const pickStock = (secucode: string) => {
    if (!date) return;
    setStockOpen(true);
    setStockLoading(true);
    setStock(null);
    getStockMinute(date.format("YYYY-MM-DD"), secucode)
      .then(setStock)
      .catch((e: any) => message.error(String(e?.message || e)))
      .finally(() => setStockLoading(false));
  };

  const s = overview?.summary;

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <Card>
        <Space>
          <Text strong>交易日</Text>
          <DatePicker
            value={date}
            onChange={(d) => d && setDate(d)}
            disabledDate={(d) => !dates.includes(d.format("YYYY-MM-DD"))}
            allowClear={false}
          />
        </Space>
      </Card>

      {loading && <Spin />}
      {!loading && !overview && <Empty description="该交易日无分时存档" />}

      {overview && s && (
        <>
          <Card title={<Title level={5} style={{ margin: 0 }}>当日汇总（收盘）</Title>}>
            <Space size="large" wrap>
              <Text>参与 <b>{s.with_pre_close}</b>/{s.total}</Text>
              <Text type="danger">涨停 {s.limit_up}</Text>
              <Text type="danger">上涨 {s.up}</Text>
              <Text type="secondary">平盘 {s.flat}</Text>
              <Text type="success">下跌 {s.down}</Text>
              <Text type="success">跌停 {s.limit_down}</Text>
            </Space>
          </Card>
          <Card title="全市场分时走势（点击曲线某时刻 → 弹出该时刻榜单）">
            <MarketOverviewChart overview={overview} onPickTime={pickTime} />
          </Card>
        </>
      )}

      <MomentRankingModal
        ranking={ranking} open={rankOpen}
        onClose={() => setRankOpen(false)} onPickStock={pickStock}
      />
      <StockMinuteDrawer
        open={stockOpen} data={stock} loading={stockLoading}
        onClose={() => setStockOpen(false)}
      />
    </Space>
  );
}
```

- [ ] **Step 2: 更新 README**

在 `README.md` 核心功能表（`## 核心功能` 的表格）加一行（置于「分时存档」行之后）：

```markdown
| 分时概览 | 单日全市场分时聚合（平均涨跌幅曲线 + 五档涨跌家数），点时刻→榜单→个股分时钻取 | ✅ |
```

在 REST API 表（`## REST / WebSocket API`）加四行（置于 `/api/archive/chip-backfill/status` 行之后）：

```markdown
| GET | `/api/market/minute/dates` | 可用分时交易日列表 |
| GET | `/api/market/minute/overview?date=` | 当日全市场分时聚合序列 + 收盘汇总 |
| GET | `/api/market/minute/ranking?date=&time=` | 某时刻全市场涨幅榜（top30 涨/跌） |
| GET | `/api/market/minute/stock?date=&secucode=` | 某股当日分时点（含涨幅） |
```

在「开发路线」的 P5 行之前加：

```markdown
- **单日全市场分时概览页（已完成）**：原「行情」tab 改名「自选行情」；新增「行情」tab 展示某交易日全市场分时聚合（mootdx `stocks().pre_close` 作昨收，等权平均涨跌幅 + 五档涨跌家数），点时刻钻取榜单、再钻取个股分时抽屉。spec `docs/superpowers/specs/2026-06-22-market-minute-overview-design.md`，plan `docs/superpowers/plans/2026-06-22-market-minute-overview.md`
```

- [ ] **Step 3: 全量后端测试**

Run: `cd backend && .venv/Scripts/python.exe -m pytest`
Expected: 全绿（新增 test_market_minute + test_api_market，原有不回归）

- [ ] **Step 4: 全量前端检查**

Run: `cd frontend && npm run lint && npm run build && npx vitest run`
Expected: lint 无错、build 通过、vitest 全绿

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/MarketMinutePage.tsx README.md
git commit -m "feat(market-minute): 串接钻取链路 + README 更新"
```

---

## 完成标准

- 「自选行情」tab（`/`）与「行情」tab（`/market`）并存，导航高亮正确。
- `/market` 选某交易日：上方平均涨跌幅曲线 + 下方五档家数柱；点击曲线某时刻弹出 top30 涨/跌榜单；点榜单行右侧抽屉显示该股当天分时小图。
- 后端 `pytest` 全绿（新增 2 个测试文件），前端 `lint`/`build`/`vitest` 全绿。
- migration `0007` 可 `upgrade head` / `downgrade -1`。
```
