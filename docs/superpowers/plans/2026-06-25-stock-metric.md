# stock_metric 指标物化表 Implementation Plan（选股筛选器阶段2）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把选股筛选器从"查询时实时算 5400 股指标（5-15s）"改为"盘后预计算物化到 stock_metric 表，查询时查表（<200ms）"，并统一 screener 与副图数据源。

**Architecture:** 每日 16:15 cron（紧接 16:10 日K回档后）遍历全市场 daily_kline → compute_indicators → upsert stock_metric（每股每日一行）；screener 改查 stock_metric 最新日；副图改查 stock_metric 时序（不足回退实时算）。

**Tech Stack:** FastAPI + SQLAlchemy async + PostgreSQL + NumPy（后端）；React 19 + TypeScript + AntD（前端）。

**Spec:** `docs/superpowers/specs/2026-06-25-stock-metric-design.md`

## Global Constraints

- Python 3.12，全 async；sync 库（mootdx）必须 `run_in_executor`。
- DB upsert 一律 PostgreSQL `ON CONFLICT DO UPDATE`（见 `ingest.py`）。
- `secucode` = `{code}.{market}`（如 `600519.SH`）。
- 测试用**真 PostgreSQL**（`conftest.py` 每 test `drop_all + create_all` + TRUNCATE）；DB 不 mock。
- Git commit **无** Co-authored-by / Claude 签名（项目约定）。
- 前端测试**不用** jest-dom matcher（`tsconfig.app.json` types 仅 `vite/client`，`toBeInTheDocument` 在 `tsc -b` 下报 TS2339）——用 `getByText`/`waitFor`/`vi.mock` 捕获断言，参照 `ScreenerPage.test.tsx`/`MarketOverviewChart.test.tsx`。
- `stock_metric` 是指标物化表，每股每日一行；预计算只读已入库 `daily_kline`，**不依赖 TdxClient**。

---

## File Structure

**后端（新建）**
- `backend/app/models/stock_metric.py` — `StockMetric` ORM model。
- `backend/app/services/metric_archive.py` — `archive_daily_metrics` + `archive_metrics_range` + 进程内状态函数。
- `backend/tests/test_metric_archive.py`

**后端（修改）**
- `backend/app/services/ingest.py` — 加 `upsert_stock_metric`。
- `backend/app/api/archive.py` — 加 `POST /api/archive/metrics` + `GET /api/archive/metrics/status`。
- `backend/app/api/screener.py` — 改查 `stock_metric`（删 daily_kline 实时算路径）。
- `backend/app/api/stocks.py` — `GET /{secucode}/indicators` 改查 `stock_metric` + 不足回退。
- `backend/app/scheduler.py` — 加 `daily_metrics_archive` cron（16:15）。
- `backend/tests/conftest.py` — `_TRUNCATE_TABLES` 加 `stock_metric` + import model。
- `backend/tests/test_api_screener.py` / `test_api_stocks.py` — 改为 seed `stock_metric`。
- `backend/alembic/versions/0008_stock_metric.py` — 新建表 migration（autogenerate）。

**前端（修改）**
- `frontend/src/api/archive.ts` — 加 `triggerMetricsArchive` / `getMetricsArchiveStatus`。
- `frontend/src/pages/ArchivePage.tsx` — 加第 4 个 Card「指标物化」。

---

## Task 1: StockMetric model + upsert + migration + conftest

**Files:**
- Create: `backend/app/models/stock_metric.py`
- Modify: `backend/app/services/ingest.py`（加 `upsert_stock_metric`）
- Modify: `backend/tests/conftest.py`（TRUNCATE + import）
- Create: `backend/alembic/versions/0008_stock_metric.py`（autogenerate）
- Test: `backend/tests/test_metric_archive.py`（本 task 只写 upsert 用例，service 在 Task 2）

**Interfaces:**
- Produces: `StockMetric` model（字段见下）；`upsert_stock_metric(session, rows: list[dict]) -> int`（仿 `upsert_daily_kline`，`ON CONFLICT (trade_date, secucode) DO UPDATE`）。

- [ ] **Step 1: 写 model**

```python
# backend/app/models/stock_metric.py
from datetime import date

from sqlalchemy import Date, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class StockMetric(Base):
    """指标物化表：每股每日一行的 compute_indicators 快照 + 派生信号。"""
    __tablename__ = "stock_metric"

    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    secucode: Mapped[str] = mapped_column(
        String(12), ForeignKey("stock_meta.secucode"), primary_key=True
    )
    # compute_indicators 快照
    close: Mapped[float] = mapped_column(Numeric(12, 4))
    open: Mapped[float] = mapped_column(Numeric(12, 4))
    dif: Mapped[float] = mapped_column(Numeric(14, 6))
    dea: Mapped[float] = mapped_column(Numeric(14, 6))
    hist: Mapped[float] = mapped_column(Numeric(14, 6))
    k: Mapped[float] = mapped_column(Numeric(8, 4))
    d: Mapped[float] = mapped_column(Numeric(8, 4))
    j: Mapped[float] = mapped_column(Numeric(8, 4))
    wr: Mapped[float] = mapped_column(Numeric(8, 4))
    rsi: Mapped[float] = mapped_column(Numeric(8, 4))
    prev_rsi: Mapped[float] = mapped_column(Numeric(8, 4))
    ma5: Mapped[float] = mapped_column(Numeric(12, 4))
    ma10: Mapped[float] = mapped_column(Numeric(12, 4))
    ma20: Mapped[float] = mapped_column(Numeric(12, 4))
    ma60: Mapped[float] = mapped_column(Numeric(12, 4))
    ma20_prev5: Mapped[float] = mapped_column(Numeric(12, 4))
    high20_prev: Mapped[float] = mapped_column(Numeric(12, 4))
    high60_prev: Mapped[float] = mapped_column(Numeric(12, 4))
    vol_ratio: Mapped[float] = mapped_column(Numeric(10, 4))
    pct5: Mapped[float] = mapped_column(Numeric(10, 4))
    consecutive_green: Mapped[int] = mapped_column(Integer)
    # 当日涨跌幅（从 daily_kline.pct_change 透传，供 screener 显示，非 compute_indicators 字段）
    pct_change: Mapped[float] = mapped_column(Numeric(8, 4))
    # 派生信号
    score: Mapped[int] = mapped_column(Integer)
    signal_level: Mapped[str] = mapped_column(String(16))
    macd_signal: Mapped[int] = mapped_column(Integer)
    kdj_signal: Mapped[int] = mapped_column(Integer)
    wr_signal: Mapped[int] = mapped_column(Integer)
    rsi_signal: Mapped[int] = mapped_column(Integer)
```

- [ ] **Step 2: 加 upsert_stock_metric（追加到 ingest.py）**

```python
# backend/app/services/ingest.py 顶部 import 加：
from app.models.stock_metric import StockMetric

# 追加到 ingest.py 末尾：
async def upsert_stock_metric(session, rows: list[dict]) -> int:
    """upsert 指标物化行。rows 每元素须含 trade_date/secucode + 全指标字段。
    ON CONFLICT (trade_date, secucode) DO UPDATE，幂等。"""
    if not rows:
        return 0
    stmt = insert(StockMetric).values(rows)
    first = rows[0]
    update_cols = {c: stmt.excluded[c] for c in first if c not in ("trade_date", "secucode")}
    stmt = stmt.on_conflict_do_update(
        index_elements=[StockMetric.trade_date, StockMetric.secucode], set_=update_cols
    )
    await session.execute(stmt)
    await session.commit()
    return len(rows)
```

- [ ] **Step 3: 改 conftest（TRUNCATE + import）**

```python
# backend/tests/conftest.py
# import 区追加（与现有 model import 并列）：
import app.models.stock_metric  # noqa: F401

# _TRUNCATE_TABLES 改为（末尾加 , stock_metric）：
_TRUNCATE_TABLES = (
    "stock_meta, daily_kline, top_holders, holder_summary, money_flow, "
    "chip_distribution, watchlist, minute_quote, stock_metric"
)
```

- [ ] **Step 4: 生成 migration**

```bash
cd backend && alembic revision --autogenerate -m "stock_metric 物化表"
```
检查生成的 `backend/alembic/versions/0008_*.py`：`upgrade()` 含 `op.create_table('stock_metric', ...)`（全字段）+ `op.create_index('ix_stock_metric_secucode_trade_date', ...)`；`downgrade()` 含 drop。若 autogenerate 漏了 `(secucode, trade_date)` 索引，手动补：
```python
op.create_index("ix_stock_metric_secucode_trade_date", "stock_metric", ["secucode", "trade_date"], unique=False)
```

- [ ] **Step 5: 写失败测试（upsert）**

```python
# backend/tests/test_metric_archive.py
import pytest
from datetime import date
from sqlalchemy import select
from app.models.stock_metric import StockMetric
from app.services.ingest import upsert_stock_metric


@pytest.mark.asyncio
async def test_upsert_stock_metric_inserts_and_updates(db_session):
    row = {
        "trade_date": date(2026, 6, 24), "secucode": "600519.SH",
        "close": 1680.0, "open": 1670.0, "dif": 1.0, "dea": 0.5, "hist": 1.0,
        "k": 50.0, "d": 48.0, "j": 54.0, "wr": 60.0, "rsi": 55.0, "prev_rsi": 52.0,
        "ma5": 1670.0, "ma10": 1660.0, "ma20": 1650.0, "ma60": 1600.0,
        "ma20_prev5": 1620.0, "high20_prev": 1660.0, "high60_prev": 1640.0,
        "vol_ratio": 1.5, "pct5": 3.0, "consecutive_green": 2,
        "pct_change": 1.2,
        "score": 4, "signal_level": "strong_bull",
        "macd_signal": 1, "kdj_signal": 1, "wr_signal": 1, "rsi_signal": 1,
    }
    n = await upsert_stock_metric(db_session, [row])
    assert n == 1
    got = (await db_session.execute(
        select(StockMetric).where(StockMetric.secucode == "600519.SH")
    )).scalars().one()
    assert got.score == 4 and got.signal_level == "strong_bull"

    # 幂等 update：同 PK 再写，score 改变
    row["score"] = 0
    row["signal_level"] = "neutral"
    await upsert_stock_metric(db_session, [row])
    got2 = (await db_session.execute(
        select(StockMetric).where(StockMetric.secucode == "600519.SH")
    )).scalars().one()
    assert got2.score == 0 and got2.signal_level == "neutral"
```

- [ ] **Step 6: 跑测试确认通过 + migration upgrade**

```bash
cd backend && PYTHONPATH=. python -m pytest tests/test_metric_archive.py -v
alembic upgrade head
```
Expected: 测试 PASS；`alembic upgrade head` 无报错（已在 head 则显示当前版本）。

- [ ] **Step 7: 提交**

```bash
git add backend/app/models/stock_metric.py backend/app/services/ingest.py \
        backend/tests/conftest.py backend/tests/test_metric_archive.py \
        backend/alembic/versions/0008_stock_metric.py
git commit -m "feat(metric): StockMetric model + upsert + migration 0008"
```

---

## Task 2: metric_archive 预计算服务

**Files:**
- Create: `backend/app/services/metric_archive.py`
- Test: `backend/tests/test_metric_archive.py`（追加）

**Interfaces:**
- Consumes: Task 1 的 `upsert_stock_metric`；`compute_indicators`/`score`/`signal_level`/`macd_signal`/`kdj_signal`/`wr_signal`/`rsi_signal`（`indicator.py`）；`DailyKline`。
- Produces:
  - `archive_daily_metrics(session_factory, trade_date: date, on_progress=None) -> dict`（`{trade_date, total, ok, failed}`）
  - `archive_metrics_range(session_factory, start: date, end: date, on_progress=None) -> dict`（`{start, end, days, ok, failed}`）
  - `is_metrics_archive_running / get_metrics_archive_status / set_metrics_archive_running / set_metrics_archive_status / reset_metrics_archive_state`

- [ ] **Step 1: 写失败测试（追加到 test_metric_archive.py）**

```python
# 追加到 backend/tests/test_metric_archive.py
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from app.config import get_settings
from app.models.base import Base
from app.models.kline import DailyKline
from app.models.stock import StockMeta
from sqlalchemy import text
from app.services.metric_archive import (
    archive_daily_metrics, archive_metrics_range, reset_metrics_archive_state,
)


@pytest.mark.asyncio
async def test_archive_daily_metrics_computes_and_upserts(db_session):
    # 独立 engine + factory（仿 test_kline_archive 模式，避免跨 session 刷新问题）
    engine = create_async_engine(get_settings().database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("TRUNCATE stock_meta, daily_kline, stock_metric CASCADE"))
    # seed：茅台 60 根持续上涨 → strong_bull
    async with factory() as s:
        s.add(StockMeta(secucode="600519.SH", code="600519", name="贵州茅台",
                        market="SH", secid="1.600519"))
        for i in range(60):
            s.add(DailyKline(ts=__import__("datetime").datetime(2026, 6, 1 + i, tzinfo=__import__("datetime").timezone.utc),
                             secucode="600519.SH", open=100 + i, close=100 + i, high=101 + i,
                             low=99, volume=1000, amount=1e7, turnover_rate=0, pct_change=1.0, vwap=100))
        await s.commit()

    reset_metrics_archive_state()
    result = await archive_daily_metrics(factory, date(2026, 6, 60) if False else date(2026, 8, 31))
    # 取 seed 最后一日（第60根 = 2026-06-60 不存在，改用足够大的日期覆盖全部）
    # 实际：trade_date 取 2026-08-31，func.date(ts)<=该日 → 全 60 根
    assert result["total"] == 1
    assert result["ok"] == 1 and result["failed"] == 0

    async with factory() as s:
        m = (await s.execute(select(StockMetric).where(StockMetric.secucode == "600519.SH"))).scalars().all()
        assert len(m) == 1
        assert m[0].score >= 3 and m[0].signal_level == "strong_bull"
        assert m[0].pct_change == 1.0  # 最后一根日K pct_change 透传
    await engine.dispose()
```
> 注：测试 seed 用 `datetime(2026,6,1+i)` 生成 60 根；`archive_daily_metrics(factory, date(2026,8,31))` 取 `func.date(ts) <= 2026-08-31` 的全部（60 根）。implementer 若 seed 日期跨度不同，调整 trade_date 实参确保覆盖全部 seed 根。

- [ ] **Step 2: 跑测试确认失败**

```bash
cd backend && PYTHONPATH=. python -m pytest tests/test_metric_archive.py -k archive_daily -v
```
Expected: FAIL（`ImportError: app.services.metric_archive`）

- [ ] **Step 3: 写实现**

```python
# backend/app/services/metric_archive.py
"""指标物化预计算：读 daily_kline → compute_indicators → upsert stock_metric。
不依赖 TdxClient（只读已入库日K）。仿 kline_archive 的状态/进度模式。"""
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.kline import DailyKline
from app.services.collector.types import KlineBar
from app.services.ingest import upsert_stock_metric
from app.services.indicator import (
    compute_indicators, score, signal_level,
    macd_signal, kdj_signal, wr_signal, rsi_signal,
)

_N = 60  # 每只取近 60 根

_running = False
_status: dict | None = None


def get_metrics_archive_status() -> dict | None:
    return _status


def is_metrics_archive_running() -> bool:
    return _running


def set_metrics_archive_running(value: bool) -> None:
    global _running
    _running = value


def set_metrics_archive_status(value: dict | None) -> None:
    global _status
    _status = value


def reset_metrics_archive_state() -> None:
    global _running, _status
    _running = False
    _status = None


async def _latest_bars(session: AsyncSession, secucode: str, trade_date: date, n: int = _N):
    rows = (await session.execute(
        select(DailyKline).where(
            DailyKline.secucode == secucode, func.date(DailyKline.ts) <= trade_date
        ).order_by(DailyKline.ts.desc()).limit(n)
    )).scalars().all()
    return list(reversed(rows))


async def archive_daily_metrics(
    session_factory: "async_sessionmaker[AsyncSession]", trade_date: date, on_progress=None
) -> dict:
    """对全市场（daily_kline 有数据的股）算 trade_date 当日指标快照并 upsert。"""
    async with session_factory() as session:
        secucodes = list((await session.execute(
            select(DailyKline.secucode).where(func.date(DailyKline.ts) <= trade_date).distinct()
        )).scalars())

    total = len(secucodes)
    ok, failed = 0, 0
    for i, secucode in enumerate(secucodes, 1):
        try:
            async with session_factory() as session:
                rows = await _latest_bars(session, secucode, trade_date)
                if len(rows) < 30:
                    failed += 1
                    if on_progress:
                        on_progress(i, total, failed)
                    continue
                bars = [
                    KlineBar(str(r.ts.date()), float(r.open), float(r.close), float(r.high),
                             float(r.low), int(r.volume), float(r.amount), float(r.pct_change),
                             float(r.turnover_rate), float(r.vwap))
                    for r in rows
                ]
                ind = compute_indicators(bars)
                s = score(ind)
                lvl = signal_level(s)
                await upsert_stock_metric(session, [{
                    "trade_date": trade_date, "secucode": secucode,
                    "close": ind["close"], "open": ind["open"],
                    "dif": ind["dif"], "dea": ind["dea"], "hist": ind["hist"],
                    "k": ind["k"], "d": ind["d"], "j": ind["j"],
                    "wr": ind["wr"], "rsi": ind["rsi"], "prev_rsi": ind["prev_rsi"],
                    "ma5": ind["ma5"], "ma10": ind["ma10"], "ma20": ind["ma20"], "ma60": ind["ma60"],
                    "ma20_prev5": ind["ma20_prev5"], "high20_prev": ind["high20_prev"],
                    "high60_prev": ind["high60_prev"], "vol_ratio": ind["vol_ratio"],
                    "pct5": ind["pct5"], "consecutive_green": ind["consecutive_green"],
                    "pct_change": bars[-1].pct_change,
                    "score": s, "signal_level": lvl,
                    "macd_signal": macd_signal(ind), "kdj_signal": kdj_signal(ind),
                    "wr_signal": wr_signal(ind), "rsi_signal": rsi_signal(ind),
                }])
                ok += 1
        except Exception as e:
            print(f"[metric_archive] {secucode} error: {e}")
            failed += 1
        if on_progress:
            on_progress(i, total, failed)
    return {"trade_date": trade_date.strftime("%Y-%m-%d"), "total": total, "ok": ok, "failed": failed}


async def archive_metrics_range(
    session_factory: "async_sessionmaker[AsyncSession]", start: date, end: date, on_progress=None
) -> dict:
    """回填 [start, end] 区间所有实际交易日（daily_kline 有的 date(ts)）的指标。"""
    async with session_factory() as session:
        trade_days = list((await session.execute(
            select(func.date(DailyKline.ts))
            .where(DailyKline.ts >= start, DailyKline.ts < end + timedelta(days=1))
            .distinct().order_by(func.date(DailyKline.ts))
        )).scalars())

    days = len(trade_days)
    ok, failed = 0, 0
    for i, td in enumerate(trade_days, 1):
        r = await archive_daily_metrics(session_factory, td)
        ok += r["ok"]
        failed += r["failed"]
        if on_progress:
            on_progress(i, days, failed)
    return {"start": start.strftime("%Y-%m-%d"), "end": end.strftime("%Y-%m-%d"),
            "days": days, "ok": ok, "failed": failed}
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd backend && PYTHONPATH=. python -m pytest tests/test_metric_archive.py -v
```
Expected: 2 passed（upsert + archive_daily_metrics）

- [ ] **Step 5: 提交**

```bash
git add backend/app/services/metric_archive.py backend/tests/test_metric_archive.py
git commit -m "feat(metric): archive_daily_metrics + range 预计算服务"
```

---

## Task 3: metrics API 端点 + scheduler 16:15 cron

**Files:**
- Modify: `backend/app/api/archive.py`（加 metrics 端点）
- Modify: `backend/app/scheduler.py`（加 16:15 cron）
- Test: `backend/tests/test_api_archive.py`（追加 metrics 用例）

**Interfaces:**
- Consumes: Task 2 的 `archive_daily_metrics`/`archive_metrics_range` + 状态函数。
- Produces: `POST /api/archive/metrics?days=60|250|all`（202，后台跑）+ `GET /api/archive/metrics/status`（复用 `ArchiveStatusOut` schema，`trade_date` 字段表示处理中的日期/范围）。

- [ ] **Step 1: 写失败测试（追加到 test_api_archive.py）**

```python
# 追加到 backend/tests/test_api_archive.py
from app.services import metric_archive


@pytest.mark.asyncio
async def test_metrics_archive_trigger_and_status(monkeypatch):
    async def _fake_range(session_factory, start, end, on_progress=None):
        return {"start": str(start), "end": str(end), "days": 1, "ok": 1, "failed": 0}
    monkeypatch.setattr(metric_archive, "archive_metrics_range", _fake_range)
    metric_archive.reset_metrics_archive_state()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        r = await ac.post("/api/archive/metrics?days=60")
        assert r.status_code == 202
        s = await ac.get("/api/archive/metrics/status")
        assert s.status_code == 200
```

- [ ] **Step 2: 跑确认失败**

```bash
cd backend && PYTHONPATH=. python -m pytest tests/test_api_archive.py -k metrics_archive -v
```
Expected: FAIL（404，端点不存在）

- [ ] **Step 3: archive.py 加端点**

```python
# backend/app/api/archive.py 顶部 import 加：
from datetime import timedelta
from app.services.metric_archive import (
    archive_metrics_range,
    get_metrics_archive_status,
    is_metrics_archive_running,
    set_metrics_archive_running,
    set_metrics_archive_status,
)
from app.models.kline import DailyKline
from sqlalchemy import func, select

# 文件末尾追加（仿 _run_daily_kline_archive / trigger_daily_kline_archive）：
_metric_tasks: set[asyncio.Task] = set()


def _resolve_range(days_str: str) -> tuple[date, date]:
    """days=60/250 → (today-N, today)；all → (daily_kline 最早日, today)。"""
    end = _today_cst()
    if days_str == "all":
        # all 的 start 由端点异步查 daily_kline MIN(ts) 决定，此处占位返回 end-365
        return end - timedelta(days=365), end
    return end - timedelta(days=int(days_str)), end


async def _run_metrics_archive(days_str: str) -> None:
    started = _now_ts()
    end = _today_cst()
    if days_str == "all":
        async with SessionLocal() as s:
            start = (await s.execute(select(func.min(DailyKline.ts)))).scalar()
            start = start.date() if start else end - timedelta(days=365)
    else:
        start = end - timedelta(days=int(days_str))
    window = f"{start.strftime('%Y-%m-%d')}..{end.strftime('%Y-%m-%d')}"
    set_metrics_archive_status({
        "state": "running", "trade_date": window,
        "total": 0, "done": 0, "ok": 0, "failed": 0,
        "started_at": started, "finished_at": None, "error": None,
    })
    try:
        def on_progress(done, total, failed):
            set_metrics_archive_status({
                "state": "running", "trade_date": window,
                "total": total, "done": done, "ok": done - failed, "failed": failed,
                "started_at": started, "finished_at": None, "error": None,
            })
        result = await archive_metrics_range(SessionLocal, start, end, on_progress=on_progress)
        set_metrics_archive_status({
            "state": "done", "trade_date": window,
            "total": result["days"], "done": result["days"],
            "ok": result["ok"], "failed": result["failed"],
            "started_at": started, "finished_at": _now_ts(), "error": None,
        })
    except Exception as e:
        set_metrics_archive_status({
            "state": "error", "trade_date": window,
            "total": 0, "done": 0, "ok": 0, "failed": 0,
            "started_at": started, "finished_at": _now_ts(), "error": str(e),
        })
    finally:
        set_metrics_archive_running(False)


@router.post("/metrics", response_model=ArchiveTriggerResponse, status_code=202)
async def trigger_metrics_archive(days: str = Query("60")):
    if days not in ("60", "250", "all"):
        raise HTTPException(status_code=422, detail="invalid days, expected 60/250/all")
    if is_metrics_archive_running():
        raise HTTPException(status_code=409, detail="metrics archive already running")
    set_metrics_archive_running(True)
    task = asyncio.create_task(_run_metrics_archive(days))
    _metric_tasks.add(task)
    task.add_done_callback(_metric_tasks.discard)
    return ArchiveTriggerResponse(task_id=str(_now_ts()), trade_date=days)


@router.get("/metrics/status", response_model=ArchiveStatusOut | None)
async def metrics_archive_status():
    return get_metrics_archive_status()
```
> 注：`ArchiveTriggerResponse` 的 `trade_date` 字段此处复用为传回 days 参数（前端不依赖该字段语义）；`ArchiveStatusOut` 复用，`trade_date` 表示窗口 `start..end`。

- [ ] **Step 4: scheduler.py 加 16:15 cron**

```python
# backend/app/scheduler.py 顶部 import 加：
from app.services.metric_archive import archive_daily_metrics, is_metrics_archive_running

# 新增函数（放 daily_kline_archive 之后）：
async def daily_metrics_archive() -> None:
    """16:15 增量预计算全市场当日指标 → stock_metric。

    紧接 16:10 daily_kline_archive 之后，确保当日日K已入库。只读 daily_kline，
    不依赖 TdxClient。与手动 POST /api/archive/metrics 共享 is_metrics_archive_running
    互斥 flag。
    """
    if is_metrics_archive_running():
        print("[daily_metrics_archive] 已有手动触发的指标物化在跑，跳过本次 cron")
        return
    await archive_daily_metrics(SessionLocal, _today_cst())

# build_scheduler() 的 return sched 前加：
    sched.add_job(
        daily_metrics_archive, CronTrigger(hour=16, minute=15),
        id="daily_metrics_archive",
    )
# 同时更新 build_scheduler docstring 与 _amain 的启动 print，补 16:15 描述。
```

- [ ] **Step 5: 跑测试确认通过**

```bash
cd backend && PYTHONPATH=. python -m pytest tests/test_api_archive.py -k metrics_archive -v
```
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add backend/app/api/archive.py backend/app/scheduler.py backend/tests/test_api_archive.py
git commit -m "feat(metric): metrics API 端点 + scheduler 16:15 cron"
```

---

## Task 4: screener 改查 stock_metric

**Files:**
- Modify: `backend/app/api/screener.py`（删 daily_kline 实时算，改查 stock_metric）
- Test: `backend/tests/test_api_screener.py`（改 seed stock_metric）

**Interfaces:**
- Consumes: `StockMetric`（Task 1）+ `evaluate_extras`（已有）。
- Produces: `POST /api/screener` 改为查 `stock_metric` 最新日，行为/响应不变。

- [ ] **Step 1: 改测试（seed stock_metric 而非 daily_kline）**

```python
# backend/tests/test_api_screener.py 整体重写 seed + 测试：
import pytest
from datetime import date
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.models.stock import StockMeta
from app.models.stock_metric import StockMetric


def _metric(secucode, name, score, signal, macd, kdj, wr, rsi, close=100, pct=1.2):
    base = {
        "close": close, "open": close * 0.99, "dif": 1.0, "dea": 0.5, "hist": 1.0,
        "k": 50.0, "d": 48.0, "j": 54.0, "wr": 60.0, "rsi": 55.0, "prev_rsi": 52.0,
        "ma5": close, "ma10": close, "ma20": close, "ma60": close,
        "ma20_prev5": close, "high20_prev": close, "high60_prev": close,
        "vol_ratio": 2.5, "pct5": 8.0, "consecutive_green": 4, "pct_change": pct,
        "score": score, "signal_level": signal,
        "macd_signal": macd, "kdj_signal": kdj, "wr_signal": wr, "rsi_signal": rsi,
    }
    return base


async def _seed_metric(db_session, secucode, name, trade_date, **kw):
    db_session.add(StockMeta(secucode=secucode, code=secucode.split(".")[0], name=name,
                             market=secucode.split(".")[1], secid=f"{'1' if secucode.endswith('SH') else '0'}.{secucode.split('.')[0]}"))
    row = {"trade_date": trade_date, "secucode": secucode, **_metric(secucode, name, **kw)}
    db_session.add(StockMetric(**row))
    await db_session.commit()


@pytest.mark.asyncio
async def test_screener_filters_strong_bull(db_session):
    await _seed_metric(db_session, "600519.SH", "贵州茅台", date(2026, 6, 24),
                       score=4, signal="strong_bull", macd=1, kdj=1, wr=1, rsi=1)
    await _seed_metric(db_session, "000001.SZ", "平安银行", date(2026, 6, 24),
                       score=-3, signal="strong_bear", macd=-1, kdj=-1, wr=-1, rsi=-1)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        r = await ac.post("/api/screener", json={"signal": "strong_bull"})
    assert r.status_code == 200
    data = r.json()
    codes = [d["secucode"] for d in data]
    assert "600519.SH" in codes and "000001.SZ" not in codes
    hit = next(d for d in data if d["secucode"] == "600519.SH")
    assert hit["score"] >= 3 and hit["signal"] == "strong_bull"
    assert set(hit) >= {"macd", "kdj", "wr", "rsi"}


@pytest.mark.asyncio
async def test_screener_empty_when_no_metrics(db_session):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        r = await ac.post("/api/screener", json={"signal": "strong_bull"})
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_screener_volume_up_extra(db_session):
    # vol_ratio=2.5 > k=2.0 → 通过 volume_up
    await _seed_metric(db_session, "600519.SH", "贵州茅台", date(2026, 6, 24),
                       score=4, signal="strong_bull", macd=1, kdj=1, wr=1, rsi=1)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        r = await ac.post("/api/screener", json={"signal": "strong_bull",
                                                  "extras": [{"type": "volume_up"}]})
    assert r.status_code == 200
    assert any(d["secucode"] == "600519.SH" for d in r.json())
```
> 删除原 `_seed`（daily_kline 版）与旧测试体，全部改为上述 stock_metric seed。保留 `dependency_overrides[get_db]` 模式（若原文件用，沿用）。

- [ ] **Step 2: 跑确认失败**

```bash
cd backend && PYTHONPATH=. python -m pytest tests/test_api_screener.py -v
```
Expected: FAIL（screener 仍查 daily_kline，无 stock_metric 数据 / 或旧逻辑不匹配）

- [ ] **Step 3: 改 screener.py（整体替换 screen 函数体）**

```python
# backend/app/api/screener.py 整体重写：
"""选股筛选器 API：查 stock_metric 最新日（盘后预计算物化）→ signal 过滤 + extras 叠加 → score 排序。"""
from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.models.stock import StockMeta
from app.models.stock_metric import StockMetric
from app.schemas.screener import ScreenItem, ScreenRequest
from app.services.indicator import evaluate_extras

router = APIRouter(prefix="/api/screener", tags=["screener"])


def _ind_from_metric(m: StockMetric) -> dict:
    """从物化行组装 evaluate_extras 需要的 ind dict。"""
    return {
        "close": float(m.close), "open": float(m.open),
        "ma5": float(m.ma5), "ma10": float(m.ma10), "ma20": float(m.ma20), "ma60": float(m.ma60),
        "ma20_prev5": float(m.ma20_prev5), "high20_prev": float(m.high20_prev),
        "high60_prev": float(m.high60_prev), "vol_ratio": float(m.vol_ratio),
        "pct5": float(m.pct5), "consecutive_green": m.consecutive_green,
    }


@router.post("", response_model=list[ScreenItem])
async def screen(req: ScreenRequest, session: AsyncSession = Depends(get_db)):
    latest = (await session.execute(select(func.max(StockMetric.trade_date)))).scalar()
    if latest is None:
        return []  # 从未预计算 → 空列表
    rows = (await session.execute(
        select(StockMetric, StockMeta.name)
        .join(StockMeta, StockMetric.secucode == StockMeta.secucode)
        .where(StockMetric.trade_date == latest)
    )).all()

    out: list[ScreenItem] = []
    for m, name in rows:
        try:
            lvl = m.signal_level
            if req.signal and lvl != req.signal:
                continue
            if not evaluate_extras(_ind_from_metric(m), [e.model_dump() for e in req.extras]):
                continue
            out.append(ScreenItem(
                secucode=m.secucode, name=name,
                close=float(m.close), pct=float(m.pct_change),
                score=m.score, signal=lvl,
                macd=m.macd_signal, kdj=m.kdj_signal, wr=m.wr_signal, rsi=m.rsi_signal,
            ))
        except Exception as e:
            print(f"[screener] {m.secucode} error: {e}")
            continue
    out.sort(key=lambda x: x.score, reverse=(req.sort == "score_desc"))
    return out
```
> 删除原 daily_kline 查询、compute loop、KlineBar import、indicator 的 compute/score/signal_level/四信号 import（evaluate_extras 保留）。`pct` 改用物化的 `pct_change`（与阶段1 当日涨跌幅语义一致）。

- [ ] **Step 4: 跑测试确认通过**

```bash
cd backend && PYTHONPATH=. python -m pytest tests/test_api_screener.py -v
```
Expected: 3 passed

- [ ] **Step 5: 提交**

```bash
git add backend/app/api/screener.py backend/tests/test_api_screener.py
git commit -m "feat(screener): 改查 stock_metric 物化表（删实时算路径）"
```

---

## Task 5: 副图改查 stock_metric + 不足回退

**Files:**
- Modify: `backend/app/api/stocks.py`（`GET /{secucode}/indicators` 改查表 + 回退）
- Test: `backend/tests/test_api_stocks.py`（indicators 用例改 seed stock_metric + 回退用例）

**Interfaces:**
- Consumes: `StockMetric`（Task 1）+ `indicator_series`（已有，回退用）。
- Produces: 副图优先查 stock_metric，行数不足 count → 回退实时算（读 daily_kline）。

- [ ] **Step 1: 改测试（seed stock_metric + 回退用例）**

```python
# backend/tests/test_api_stocks.py 的 indicators 用例改为：
from app.models.stock_metric import StockMetric


@pytest.mark.asyncio
async def test_stock_indicators_from_metric(db_session):
    db_session.add(StockMeta(secucode="600519.SH", code="600519", name="贵州茅台",
                             market="SH", secid="1.600519"))
    # seed 60 行 stock_metric
    for i in range(60):
        db_session.add(StockMetric(
            trade_date=date(2026, 6, 1 + i), secucode="600519.SH",
            close=100 + i, open=100 + i, dif=1.0, dea=0.5, hist=1.0,
            k=50.0, d=48.0, j=54.0, wr=60.0, rsi=55.0, prev_rsi=52.0,
            ma5=100.0, ma10=100.0, ma20=100.0, ma60=100.0, ma20_prev5=100.0,
            high20_prev=100.0, high60_prev=100.0, vol_ratio=1.0, pct5=1.0,
            consecutive_green=1, pct_change=1.0,
            score=2, signal_level="bull", macd_signal=1, kdj_signal=1, wr_signal=0, rsi_signal=0,
        ))
    await db_session.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        r = await ac.get("/api/stocks/600519.SH/indicators?count=60")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 60
    assert set(data[-1]) >= {"date", "dif", "dea", "hist", "k", "d", "j", "wr", "rsi", "close"}


@pytest.mark.asyncio
async def test_stock_indicators_fallback_realtime(db_session):
    # stock_metric 不足 → 回退实时算（seed daily_kline）
    db_session.add(StockMeta(secucode="600519.SH", code="600519", name="贵州茅台",
                             market="SH", secid="1.600519"))
    for i in range(60):
        db_session.add(DailyKline(ts=datetime(2026, 6, 1 + i, tzinfo=timezone.utc),
                                  secucode="600519.SH", open=100, close=100 + i, high=101 + i,
                                  low=99, volume=1000, amount=1e7, turnover_rate=0,
                                  pct_change=1.0, vwap=100))
    await db_session.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        r = await ac.get("/api/stocks/600519.SH/indicators?count=60")
    assert r.status_code == 200
    assert len(r.json()) == 60  # 回退实时算给满 60 根
```
> 确认 `datetime`/`timezone`/`DailyKline` 在测试文件已 import（参照现有用例）。

- [ ] **Step 2: 跑确认失败**

```bash
cd backend && PYTHONPATH=. python -m pytest tests/test_api_stocks.py -k indicators -v
```
Expected: FAIL（from_metric 用例：当前实时算返回的字段虽一致但来源不同测试可能仍过；fallback 用例可能过。需确认 from_metric 断言行数。若当前实现已能让 from_metric 过，则先改实现使 from_metric 走查表路径——此步主要验证改造后行为）。实施者按实际输出判断。

- [ ] **Step 3: 改 stocks.py 的 indicators 端点**

```python
# backend/app/api/stocks.py 的 stock_indicators 端点整体替换：
from app.models.stock_metric import StockMetric
from app.services.indicator import indicator_series  # 回退用


@router.get("/{secucode}/indicators", response_model=list[dict])
async def stock_indicators(secucode: str, count: int = 60, session: AsyncSession = Depends(get_db)):
    # 优先查 stock_metric 时序
    rows = (await session.execute(
        select(StockMetric).where(StockMetric.secucode == secucode)
        .order_by(StockMetric.trade_date.desc()).limit(count)
    )).scalars().all()
    if len(rows) >= count:
        rows = list(reversed(rows))
        return [{
            "date": str(r.trade_date), "close": float(r.close),
            "dif": float(r.dif), "dea": float(r.dea), "hist": float(r.hist),
            "k": float(r.k), "d": float(r.d), "j": float(r.j),
            "wr": float(r.wr), "rsi": float(r.rsi),
        } for r in rows]
    # 不足 → 回退实时算（读 daily_kline）
    krows = (await session.execute(
        select(DailyKline).where(DailyKline.secucode == secucode)
        .order_by(DailyKline.ts.desc()).limit(count)
    )).scalars().all()
    krows = list(reversed(krows))
    if not krows:
        raise HTTPException(status_code=404, detail="no kline")
    from app.services.collector.types import KlineBar
    bars = [KlineBar(str(r.ts.date()), float(r.open), float(r.close), float(r.high),
                     float(r.low), int(r.volume), float(r.amount), float(r.pct_change),
                     float(r.turnover_rate), float(r.vwap)) for r in krows]
    return indicator_series(bars)
```
> 确认 `select`/`DailyKline`/`AsyncSession`/`get_db`/`HTTPException`/`router` 已在 stocks.py import（参照现有 K 线端点）。保留原 `indicator_series` import。

- [ ] **Step 4: 跑测试确认通过**

```bash
cd backend && PYTHONPATH=. python -m pytest tests/test_api_stocks.py -k indicators -v
```
Expected: 2 passed（from_metric + fallback）

- [ ] **Step 5: 提交**

```bash
git add backend/app/api/stocks.py backend/tests/test_api_stocks.py
git commit -m "feat(stocks): 副图改查 stock_metric + 不足回退实时算"
```

---

## Task 6: 前端 ArchivePage 指标物化 Card

**Files:**
- Modify: `frontend/src/api/archive.ts`（加 metrics API）
- Modify: `frontend/src/pages/ArchivePage.tsx`（加第 4 Card）

**Interfaces:**
- Consumes: `POST /api/archive/metrics?days=` + `GET /api/archive/metrics/status`（Task 3）。
- Produces: ArchivePage 第 4 Card「指标物化」（Select 60/250/all + 按钮 + 进度轮询）。

- [ ] **Step 1: 加 api 层（追加到 archive.ts）**

```typescript
// 追加到 frontend/src/api/archive.ts
export const triggerMetricsArchive = (days = "60") =>
  apiPost<{ task_id: string; trade_date: string }>(
    `/archive/metrics?days=${days}`
  );

export const getMetricsArchiveStatus = () =>
  apiGet<ArchiveStatus | null>("/archive/metrics/status");
```

- [ ] **Step 2: 加 Card（改 ArchivePage.tsx）**

在 `ArchivePage.tsx`：
- import 加 `getMetricsArchiveStatus, triggerMetricsArchive`。
- 组件内加 state（仿 kline 的三行）：
```typescript
const [metricStatus, setMetricStatus] = useState<ArchiveStatus | null>(null);
const [metricDays, setMetricDays] = useState<string>("60");
const [metricLoading, setMetricLoading] = useState(false);
```
- 加 useEffect 轮询（仿「日K回档」的 useEffect，调 `getMetricsArchiveStatus`，`setInterval` 2000）。
- 加 `triggerMetric` 函数（仿 `triggerKline`，调 `triggerMetricsArchive(metricDays)`，catch 用 `e: unknown` + `String((e as Error|undefined)?.message ?? e)`，409→warning）。
- 加派生量 `metricRunning`/`metricPct`（仿 `klineRunning`/`klinePct`）。
- 在「日K回档」Card 之后追加第 4 个 Card（仿其结构，title="指标物化"，文案"盘后预计算全市场技术指标（MACD/KDJ/WR/RSI 共振）入 stock_metric，每日 16:15 增量。选股筛选/副图查此表，秒级响应。首次可选 60/250/all 回填历史。"，Select options `60/250/all`，字段用 `metricStatus`/`metricDays`/`metricLoading`/`metricRunning`/`metricPct`/`triggerMetric`，Tag 显示 `metricStatus.trade_date`（窗口 start..end））。

完整 Card JSX（插在「日K回档」Card `</Card>` 之后、最外层 `</Space>` 之前）：
```tsx
      <Card title="指标物化">
        <Space direction="vertical" size="middle" style={{ width: "100%" }}>
          <div>
            <Text type="secondary">
              盘后预计算全市场技术指标（MACD/KDJ/WR/RSI 共振）入 stock_metric，每日 16:15 增量。
              选股筛选/副图查此表，秒级响应。首次可选 60/250/all 回填历史。
            </Text>
          </div>
          <Space>
            <Select
              value={metricDays}
              onChange={setMetricDays}
              style={{ width: 140 }}
              options={[
                { value: "60", label: "最近 60 天" },
                { value: "250", label: "最近 250 天" },
                { value: "all", label: "全部（daily_kline 已有）" },
              ]}
            />
            <Button
              type="primary"
              loading={metricLoading}
              onClick={triggerMetric}
              disabled={metricRunning}
            >
              {metricRunning ? "物化中…" : "开始物化"}
            </Button>
          </Space>
          {metricStatus && metricStatus.state && (
            <div>
              <Space>
                <Tag color={metricStatus.state === "done" ? "green" : metricStatus.state === "error" ? "red" : "blue"}>
                  {metricStatus.state}
                </Tag>
                <Text>窗口：{metricStatus.trade_date ?? "-"}</Text>
              </Space>
              <Progress
                percent={metricPct}
                status={metricStatus.state === "error" ? "exception" : metricRunning ? "active" : "normal"}
              />
              <Space size="large">
                <Text>总计 {metricStatus.total}</Text>
                <Text type="success">成功 {metricStatus.ok}</Text>
                <Text type="danger">失败 {metricStatus.failed}</Text>
              </Space>
              {metricStatus.error && <Text type="danger">错误：{metricStatus.error}</Text>}
            </div>
          )}
        </Space>
      </Card>
```

- [ ] **Step 3: build + lint 核实**

```bash
cd frontend && npm run build
```
Expected: build 通过（既有 eslint 技术债不阻塞 build；新代码用 `e: unknown` 避免 no-explicit-any）。

- [ ] **Step 4: 提交**

```bash
git add frontend/src/api/archive.ts frontend/src/pages/ArchivePage.tsx
git commit -m "feat(archive): ArchivePage 指标物化 Card（60/250/all 回填 + 进度）"
```

---

## Self-Review

**1. Spec 覆盖**
- stock_metric 表 + 字段 + migration → Task 1 ✓
- 预计算服务 archive_daily_metrics + range + 状态 → Task 2 ✓
- 16:15 cron + 手动 API + status → Task 3 ✓
- screener 改查表（evaluate_extras 保留动态）→ Task 4 ✓
- 副图改查表 + 不足回退 → Task 5 ✓
- ArchivePage Card → Task 6 ✓
- 测试每 task 内 ✓；conftest TRUNCATE 覆盖 stock_metric → Task 1 ✓
- 非目标（向量化 compute、筹码全市场、盘中实时）未越界 ✓
- spec 细化：`pct_change` 字段（screener 当日涨跌幅，compute_indicators 无此字段，从 daily_kline 透传）→ Task 1 model + Task 2 archive + Task 4 screener 一致 ✓

**2. 占位扫描**
- 无 TBD/TODO。Task 5 Step 2 的 Expected 描述了"按实际输出判断"（因 from_metric 用例在改造前后行为都可能 60 根），这是诚实的测试前置说明，非占位。Task 6 Step 2 的"仿 X 结构"附了完整 JSX，非占位。

**3. 类型/命名一致性**
- `StockMetric` 字段在 Task 1 定义，Task 2 archive row dict、Task 4 `_ind_from_metric`、Task 5 副图映射、Task 1/4/5 测试 seed 全部对齐（close/open/dif/dea/hist/k/d/j/wr/rsi/prev_rsi/ma5/10/20/60/ma20_prev5/high20_prev/high60_prev/vol_ratio/pct5/consecutive_green/pct_change/score/signal_level/macd_signal/kdj_signal/wr_signal/rsi_signal）✓
- `archive_daily_metrics`/`archive_metrics_range` 签名 Task 2 定义、Task 3 调用一致 ✓
- 状态函数命名 `is_metrics_archive_running`/`get_metrics_archive_status`/`set_*`/`reset_metrics_archive_state` Task 2 定义、Task 3（archive.py + scheduler.py）调用一致 ✓
- `upsert_stock_metric(session, rows)` Task 1 定义、Task 2 调用一致 ✓
- `pct` 字段：Task 4 用 `m.pct_change`（物化），与阶段1 ScreenItem.pct=当日涨跌幅 语义一致 ✓

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-25-stock-metric.md`. Two execution options:

**1. Subagent-Driven (recommended)** — 每个 Task 派一个全新 subagent 实现，任务间两段式 review，迭代快、上下文干净。

**2. Inline Execution** — 在本会话用 executing-plans 批量执行，带 checkpoint 审查。

选哪种？
