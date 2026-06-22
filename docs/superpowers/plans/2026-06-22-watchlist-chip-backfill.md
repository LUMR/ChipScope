# 自选股筹码补全 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在「数据存档」页加一个按钮，一键对所有自选股重新拉日K并全量重算筹码分布，补齐因停机/漏采缺失的历史日期筹码。

**Architecture:** 新建 `services/chip_backfill.py`（遍历 watchlist → 逐只 `ingest_kline_and_chips`，带进度回调 + 进程内状态，与 `minute_archive.py` 对称）；在 `api/archive.py` 加 2 个端点（fire-and-forget + 三态状态轮询，复刻分时存档）；前端 `ArchivePage` 加第二个 Card（窗口 Select 120/365/全部 + Progress）。

**Tech Stack:** FastAPI · SQLAlchemy 2 async · httpx (ASGITransport 测试) · React 19 + Ant Design + Vite

**关键机制（必须理解）：** `compute_chip_series` 是全量重算 + `ON CONFLICT` 幂等覆盖，所以「补全缺失」= 跑一次 `ingest_kline_and_chips(days)`，该股全部历史日期筹码一次性补齐，无需挑日期。

---

## 文件结构

| 文件 | 操作 | 责任 |
|---|---|---|
| `backend/app/services/chip_backfill.py` | 新建 | `parse_days` 纯函数 + `ALL_DAYS` 常量 + 进程内状态 get/set/is/reset + `backfill_watchlist_chips` 编排 |
| `backend/tests/test_chip_backfill.py` | 新建 | `parse_days`/状态/编排主流程测试 |
| `backend/app/schemas/archive.py` | 修改 | 加 `BackfillStatusOut` + `BackfillTriggerResponse` |
| `backend/app/api/archive.py` | 修改 | 加 `POST /chip-backfill` + `GET /chip-backfill/status` + `_run_chip_backfill` 后台任务 |
| `backend/tests/test_archive_api.py` | 修改 | 加 4 个筹码补全端点测试 |
| `frontend/src/api/archive.ts` | 修改 | 加 `BackfillStatus` 类型 + `triggerChipBackfill` + `getChipBackfillStatus` |
| `frontend/src/pages/ArchivePage.tsx` | 修改 | 加第二个 Card「自选股筹码补全」 |
| `README.md` | 修改 | 核心功能表 / API 表 / 开发路线 补筹码补全 |

**无需注册 router**：`archive_router` 已在 `app/main.py:59` 注册，新端点加在 router 内自动生效。

**Git 约定**：commit message 不带 Co-authored-by / Claude 签名（项目 CLAUDE.md 规定）。

---

### Task 1: `chip_backfill.py` — `parse_days` 纯函数 + `ALL_DAYS` + 进程内状态

**Files:**
- Create: `backend/app/services/chip_backfill.py`
- Test: `backend/tests/test_chip_backfill.py`

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_chip_backfill.py`：

```python
"""自选股筹码补全：parse_days / 进程内状态 / 编排主流程测试。"""
import pytest

from app.services.chip_backfill import (
    ALL_DAYS,
    parse_days,
    get_backfill_status,
    set_backfill_status,
    is_backfill_running,
    set_backfill_running,
    reset_backfill_state,
)


def test_parse_days_all():
    assert parse_days("all") == ALL_DAYS


def test_parse_days_numeric():
    assert parse_days("120") == 120
    assert parse_days("365") == 365


def test_parse_days_invalid():
    with pytest.raises(ValueError):
        parse_days("999")
    with pytest.raises(ValueError):
        parse_days("")


def test_state_get_set_reset():
    reset_backfill_state()
    assert get_backfill_status() is None
    assert is_backfill_running() is False
    set_backfill_running(True)
    assert is_backfill_running() is True
    set_backfill_status({"state": "running", "window": "365"})
    assert get_backfill_status() == {"state": "running", "window": "365"}
    reset_backfill_state()
    assert get_backfill_status() is None
    assert is_backfill_running() is False
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_chip_backfill.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.chip_backfill'`

- [ ] **Step 3: 写最小实现**

创建 `backend/app/services/chip_backfill.py`（编排函数 `backfill_watchlist_chips` 留到 Task 2，本任务只写 parse_days + 状态）：

```python
"""自选股筹码补全：遍历 watchlist → 逐只 ingest_kline_and_chips 全量重算筹码。

与 services/minute_archive.py 对称：编排主流程 + 进程内状态（单进程 API/cron 共享）。
"""
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

ALL_DAYS = 1000  # UI「全部」窗口：约 3-4 年日K；mootdx bars(offset) 无硬上限，1000 足够

_VALID_DAYS = {"120": 120, "365": 365}


def parse_days(s: str) -> int:
    """UI 窗口字符串 → ingest 的 count。

    "all" → ALL_DAYS；"120"/"365" → 对应整数；其他 → ValueError（端点层捕获返 422）。
    """
    if s == "all":
        return ALL_DAYS
    if s in _VALID_DAYS:
        return _VALID_DAYS[s]
    raise ValueError(f"invalid days: {s!r}")


# ---- 进程内状态（单进程模式：API 与 cron 同进程可见；非 Redis）----
_backfill_running: bool = False
_backfill_status: dict | None = None


def get_backfill_status() -> dict | None:
    return _backfill_status


def is_backfill_running() -> bool:
    return _backfill_running


def set_backfill_running(value: bool) -> None:
    global _backfill_running
    _backfill_running = value


def set_backfill_status(value: dict | None) -> None:
    global _backfill_status
    _backfill_status = value


def reset_backfill_state() -> None:
    """测试用：清理模块级状态。"""
    global _backfill_running, _backfill_status
    _backfill_running = False
    _backfill_status = None
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_chip_backfill.py -v`
Expected: PASS — 4 passed

- [ ] **Step 5: 提交**

```bash
git -C D:/Codes/ChipScope add backend/app/services/chip_backfill.py backend/tests/test_chip_backfill.py
git -C D:/Codes/ChipScope commit -m "feat(chip-backfill): parse_days 纯函数 + 进程内状态"
```

---

### Task 2: `chip_backfill.py` — `backfill_watchlist_chips` 编排主流程

**Files:**
- Modify: `backend/app/services/chip_backfill.py`（加编排函数 + 顶部 import）
- Test: `backend/tests/test_chip_backfill.py`（加主流程测试）

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_chip_backfill.py` 末尾追加：

```python
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.models.base import Base
from app.models.stock import StockMeta
from app.models.watchlist import Watchlist
from app.services import chip_backfill


@pytest.mark.asyncio
async def test_backfill_watchlist_chips_main_flow(monkeypatch):
    """遍历 watchlist 逐只 ingest：第 2 只抛错计 failed，on_progress 末次为完成态。"""
    engine = create_async_engine(get_settings().database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text(
            "TRUNCATE stock_meta, watchlist, daily_kline, chip_distribution CASCADE"
        ))
    async with factory() as s:
        s.add_all([
            StockMeta(secucode="600519.SH", code="600519", name="贵州茅台",
                      market="SH", secid="1.600519"),
            StockMeta(secucode="000001.SZ", code="000001", name="平安银行",
                      market="SZ", secid="0.000001"),
            Watchlist(secucode="600519.SH", scope="default", sort_order=0),
            Watchlist(secucode="000001.SZ", scope="default", sort_order=1),
        ])
        await s.commit()

    calls = []

    async def fake_ingest(tdx, em, session, secucode, secid, *, days):
        calls.append((secucode, days))
        if secucode == "000001.SZ":
            raise RuntimeError("boom")
        return {"klines": 3, "chips": 3}

    monkeypatch.setattr(chip_backfill, "ingest_kline_and_chips", fake_ingest)

    progress = []
    result = await chip_backfill.backfill_watchlist_chips(
        factory, tdx=None, em=None, days=365,
        on_progress=lambda done, total, ok, failed: progress.append((done, total, ok, failed)),
    )

    assert result == {"total": 2, "ok": 1, "failed": 1}
    assert calls == [("600519.SH", 365), ("000001.SZ", 365)]
    assert progress[-1] == (2, 2, 1, 1)  # 末次进度为完成态
    await engine.dispose()


@pytest.mark.asyncio
async def test_backfill_watchlist_empty(monkeypatch):
    """watchlist 为空 → total=0，正常完成（非错误）。"""
    engine = create_async_engine(get_settings().database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("TRUNCATE stock_meta, watchlist CASCADE"))

    async def _never(*a, **kw):
        pytest.fail("空 watchlist 不应调用 ingest")

    monkeypatch.setattr(chip_backfill, "ingest_kline_and_chips", _never)
    result = await chip_backfill.backfill_watchlist_chips(factory, None, None, days=120)
    assert result == {"total": 0, "ok": 0, "failed": 0}
    await engine.dispose()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_chip_backfill.py::test_backfill_watchlist_chips_main_flow -v`
Expected: FAIL — `AttributeError: module 'app.services.chip_backfill' has no attribute 'backfill_watchlist_chips'`

- [ ] **Step 3: 写最小实现**

修改 `backend/app/services/chip_backfill.py`：

在顶部 import 区（`from sqlalchemy.ext.asyncio...` 之后）加：

```python
from sqlalchemy import select

from app.models.stock import StockMeta
from app.models.watchlist import Watchlist
from app.services.kline_chip import ingest_kline_and_chips

SCOPE = "default"
```

在文件末尾（`reset_backfill_state` 之后）加编排函数：

```python
async def backfill_watchlist_chips(
    session_factory: async_sessionmaker[AsyncSession],
    tdx,
    em,
    days: int,
    on_progress=None,
) -> dict:
    """遍历 watchlist 自选股 → 逐只 ingest_kline_and_chips(days) 全量重算筹码。

    复用单 session + 单 tdx + 单 em（与 scheduler.daily_kline_chip 一致）。
    单只抛错计 failed 不中断；on_progress(done, total, ok, failed) 每只调用一次。
    返回 {total, ok, failed}。
    """
    async with session_factory() as session:
        rows = (
            await session.execute(
                select(Watchlist.secucode, StockMeta.secid)
                .join(StockMeta, Watchlist.secucode == StockMeta.secucode)
                .where(Watchlist.scope == SCOPE)
                .order_by(Watchlist.sort_order)
            )
        ).all()
        total = len(rows)
        ok = 0
        failed = 0
        for i, (secucode, secid) in enumerate(rows, 1):
            try:
                await ingest_kline_and_chips(
                    tdx, em, session, secucode, secid, days=days
                )
                ok += 1
            except Exception as e:  # 单只失败不影响其他
                print(f"[backfill] {secucode} error: {e}")
                failed += 1
            if on_progress is not None:
                on_progress(i, total, ok, failed)
    return {"total": total, "ok": ok, "failed": failed}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_chip_backfill.py -v`
Expected: PASS — 6 passed

- [ ] **Step 5: 提交**

```bash
git -C D:/Codes/ChipScope add backend/app/services/chip_backfill.py backend/tests/test_chip_backfill.py
git -C D:/Codes/ChipScope commit -m "feat(chip-backfill): backfill_watchlist_chips 编排主流程"
```

---

### Task 3: `schemas/archive.py` — `BackfillStatusOut` + `BackfillTriggerResponse`

**Files:**
- Modify: `backend/app/schemas/archive.py`

- [ ] **Step 1: 实现（纯 Pydantic 模型，靠 Task 4 的 API 测试覆盖）**

在 `backend/app/schemas/archive.py` 末尾追加：

```python
class BackfillStatusOut(BaseModel):
    state: str | None = None          # running / done / error
    window: str | None = None         # "120" / "365" / "all"
    total: int = 0
    done: int = 0       # 已处理（含 failed），进度 = done/total
    ok: int = 0
    failed: int = 0
    started_at: int | None = None
    finished_at: int | None = None
    error: str | None = None


class BackfillTriggerResponse(BaseModel):
    task_id: str
    window: str
```

- [ ] **Step 2: 导入冒烟（确认无语法错）**

Run: `cd backend && .venv/Scripts/python -c "from app.schemas.archive import BackfillStatusOut, BackfillTriggerResponse; print('ok')"`
Expected: `ok`

- [ ] **Step 3: 提交**

```bash
git -C D:/Codes/ChipScope add backend/app/schemas/archive.py
git -C D:/Codes/ChipScope commit -m "feat(chip-backfill): BackfillStatusOut/TriggerResponse schema"
```

---

### Task 4: `api/archive.py` — 2 个端点 + `_run_chip_backfill` 后台任务

**Files:**
- Modify: `backend/app/api/archive.py`
- Test: `backend/tests/test_archive_api.py`

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_archive_api.py`：

顶部 import 修改——把：
```python
from app.services.minute_archive import reset_archive_state, set_archive_status
```
改为：
```python
from app.services.minute_archive import reset_archive_state, set_archive_status
from app.services.chip_backfill import (
    reset_backfill_state,
    set_backfill_running,
    set_backfill_status,
)
```

`_clean_state` fixture 修改——把：
```python
@pytest.fixture(autouse=True)
def _clean_state():
    reset_archive_state()
    yield
    reset_archive_state()
```
改为：
```python
@pytest.fixture(autouse=True)
def _clean_state():
    reset_archive_state()
    reset_backfill_state()
    yield
    reset_archive_state()
    reset_backfill_state()
```

在文件末尾追加 4 个测试：

```python
@pytest.mark.asyncio
async def test_chip_backfill_status_empty():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/api/archive/chip-backfill/status")
        assert r.status_code == 200
        assert r.json() is None  # 初始无状态


@pytest.mark.asyncio
async def test_chip_backfill_trigger_then_status(monkeypatch):
    import app.api.archive as arch
    import asyncio

    async def _fake_run(days_str):
        set_backfill_status({
            "state": "done", "window": days_str,
            "total": 2, "done": 2, "ok": 2, "failed": 0,
        })
    monkeypatch.setattr(arch, "_run_chip_backfill", _fake_run)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/api/archive/chip-backfill", params={"days": "365"})
        assert r.status_code == 202
        assert r.json()["window"] == "365"
        await asyncio.sleep(0.1)
        s = await ac.get("/api/archive/chip-backfill/status")
        assert s.status_code == 200
        body = s.json()
        assert body["state"] == "done"
        assert body["window"] == "365"
        assert body["ok"] == 2


@pytest.mark.asyncio
async def test_chip_backfill_rejects_when_running():
    set_backfill_running(True)  # 预置为运行中
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/api/archive/chip-backfill", params={"days": "365"})
        assert r.status_code == 409


@pytest.mark.asyncio
async def test_chip_backfill_bad_days_returns_422():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/api/archive/chip-backfill", params={"days": "999"})
        assert r.status_code == 422
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_archive_api.py -v`
Expected: FAIL — 新增 4 个测试因路由 404 / `_run_chip_backfill` 不存在而失败

- [ ] **Step 3: 写最小实现**

修改 `backend/app/api/archive.py`。

import 区加（在现有 `from app.services.collector.tdx_client import TdxClient` 附近）：

```python
from app.services.collector.eastmoney import EastMoneyClient
from app.services.chip_backfill import (
    backfill_watchlist_chips,
    get_backfill_status,
    is_backfill_running,
    parse_days,
    set_backfill_running,
    set_backfill_status,
)
from app.schemas.archive import BackfillStatusOut, BackfillTriggerResponse
```

（`ArchiveStatusOut`/`ArchiveTriggerResponse` 的现有 import 行保留不动。）

在文件末尾追加后台任务 + 调度 + 2 个端点：

```python
async def _run_chip_backfill(days_str: str) -> None:
    """后台补全：复用一个 TdxClient + EastMoneyClient，全程更新内存状态。异常写 error。"""
    started = _now_ts()
    days = parse_days(days_str)  # 端点已校验过，此处再解析取 int
    set_backfill_status({
        "state": "running", "window": days_str,
        "total": 0, "done": 0, "ok": 0, "failed": 0,
        "started_at": started, "finished_at": None, "error": None,
    })
    tdx = TdxClient()
    try:
        async with EastMoneyClient() as em:
            def on_progress(done, total, ok, failed):
                set_backfill_status({
                    "state": "running", "window": days_str,
                    "total": total, "done": done, "ok": ok, "failed": failed,
                    "started_at": started, "finished_at": None, "error": None,
                })
            result = await backfill_watchlist_chips(
                SessionLocal, tdx, em, days, on_progress=on_progress
            )
        set_backfill_status({
            "state": "done", "window": days_str,
            "total": result["total"], "done": result["total"],
            "ok": result["ok"], "failed": result["failed"],
            "started_at": started, "finished_at": _now_ts(), "error": None,
        })
    except Exception as e:
        set_backfill_status({
            "state": "error", "window": days_str,
            "total": 0, "done": 0, "ok": 0, "failed": 0,
            "started_at": started, "finished_at": _now_ts(), "error": str(e),
        })
    finally:
        tdx.close()
        set_backfill_running(False)


def _schedule_chip_backfill(days_str: str) -> None:
    set_backfill_running(True)
    task = asyncio.create_task(_run_chip_backfill(days_str))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


@router.post("/chip-backfill", response_model=BackfillTriggerResponse, status_code=202)
async def trigger_chip_backfill(days: str = Query(...)):
    if is_backfill_running():
        raise HTTPException(status_code=409, detail="chip backfill already running")
    try:
        parse_days(days)
    except ValueError:
        raise HTTPException(status_code=422, detail="invalid days, expected 120/365/all")
    _schedule_chip_backfill(days)
    return BackfillTriggerResponse(task_id=str(_now_ts()), window=days)


@router.get("/chip-backfill/status", response_model=BackfillStatusOut | None)
async def chip_backfill_status():
    return get_backfill_status()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_archive_api.py -v`
Expected: PASS — 全部（含原有 4 个分时存档测试 + 新增 4 个筹码补全测试）

- [ ] **Step 5: 提交**

```bash
git -C D:/Codes/ChipScope add backend/app/api/archive.py backend/tests/test_archive_api.py
git -C D:/Codes/ChipScope commit -m "feat(chip-backfill): POST/GET 端点 + 后台任务"
```

---

### Task 5: 前端 `api/archive.ts` — 类型 + 2 个调用函数

**Files:**
- Modify: `frontend/src/api/archive.ts`

- [ ] **Step 1: 实现**

在 `frontend/src/api/archive.ts` 末尾追加：

```typescript
export interface BackfillStatus {
  state: "running" | "done" | "error" | null;
  window: string | null;
  total: number;
  done: number;
  ok: number;
  failed: number;
  started_at: number | null;
  finished_at: number | null;
  error: string | null;
}

export const triggerChipBackfill = (days: string) =>
  apiPost<{ task_id: string; window: string }>(
    `/archive/chip-backfill?days=${days}`
  );

export const getChipBackfillStatus = () =>
  apiGet<BackfillStatus | null>("/archive/chip-backfill/status");
```

- [ ] **Step 2: 类型检查**

Run: `cd frontend && npx tsc -b --noEmit`
Expected: 无错误

- [ ] **Step 3: 提交**

```bash
git -C D:/Codes/ChipScope add frontend/src/api/archive.ts
git -C D:/Codes/ChipScope commit -m "feat(chip-backfill): 前端 api 调用 + BackfillStatus 类型"
```

---

### Task 6: 前端 `ArchivePage.tsx` — 第二个 Card「自选股筹码补全」

**Files:**
- Modify: `frontend/src/pages/ArchivePage.tsx`

- [ ] **Step 1: 实现（替换整个文件）**

用以下内容替换 `frontend/src/pages/ArchivePage.tsx`：

```tsx
import { Button, Card, DatePicker, message, Progress, Select, Space, Tag, Typography } from "antd";
import dayjs from "dayjs";
import { useEffect, useState } from "react";
import type { ArchiveStatus, BackfillStatus } from "../api/archive";
import {
  getArchiveStatus,
  getChipBackfillStatus,
  triggerArchive,
  triggerChipBackfill,
} from "../api/archive";

const { Text } = Typography;

export default function ArchivePage() {
  const [status, setStatus] = useState<ArchiveStatus | null>(null);
  const [date, setDate] = useState<dayjs.Dayjs | null>(null);
  const [loading, setLoading] = useState(false);

  const [backfillStatus, setBackfillStatus] = useState<BackfillStatus | null>(null);
  const [window, setWindow] = useState<string>("365");
  const [backfillLoading, setBackfillLoading] = useState(false);

  // 分时存档：首次加载 + 运行中轮询
  useEffect(() => {
    getArchiveStatus().then(setStatus);
    const timer = setInterval(async () => {
      try {
        setStatus(await getArchiveStatus());
      } catch {
        /* ignore */
      }
    }, 2000);
    return () => clearInterval(timer);
  }, []);

  // 筹码补全：首次加载 + 运行中轮询
  useEffect(() => {
    getChipBackfillStatus().then(setBackfillStatus);
    const timer = setInterval(async () => {
      try {
        setBackfillStatus(await getChipBackfillStatus());
      } catch {
        /* ignore */
      }
    }, 2000);
    return () => clearInterval(timer);
  }, []);

  const trigger = async () => {
    setLoading(true);
    try {
      const dateStr = date ? date.format("YYYY-MM-DD") : undefined;
      await triggerArchive(dateStr);
      message.success("已开始存档，请关注进度");
    } catch (e: any) {
      const msg = String(e?.message || e);
      if (msg.includes("409")) {
        message.warning("已有存档任务在运行");
      } else {
        message.error(msg);
      }
    } finally {
      setLoading(false);
    }
  };

  const triggerBackfill = async () => {
    setBackfillLoading(true);
    try {
      await triggerChipBackfill(window);
      message.success("已开始补全，请关注进度");
    } catch (e: any) {
      const msg = String(e?.message || e);
      if (msg.includes("409")) {
        message.warning("已有补全任务在运行");
      } else {
        message.error(msg);
      }
    } finally {
      setBackfillLoading(false);
    }
  };

  const running = status?.state === "running";
  const pct =
    status && status.total > 0
      ? Math.round((status.done / status.total) * 100)
      : 0;

  const backfillRunning = backfillStatus?.state === "running";
  const backfillPct =
    backfillStatus && backfillStatus.total > 0
      ? Math.round((backfillStatus.done / backfillStatus.total) * 100)
      : 0;

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%", maxWidth: 720 }}>
      <Card title="分时行情存档">
        <Space direction="vertical" size="middle" style={{ width: "100%" }}>
          <div>
            <Text type="secondary">
              把全市场沪深 A 股当天分时数据（每只 ~240 个分钟点）落库。
              默认当天，可选历史日（仅最近若干交易日可补）。
            </Text>
          </div>
          <Space>
            <DatePicker
              value={date}
              onChange={setDate}
              placeholder="留空=当天"
              allowClear
            />
            <Button type="primary" loading={loading} onClick={trigger} disabled={running}>
              {running ? "存档中…" : "开始存档"}
            </Button>
          </Space>
          {status && status.state && (
            <div>
              <Space>
                <Tag color={status.state === "done" ? "green" : status.state === "error" ? "red" : "blue"}>
                  {status.state}
                </Tag>
                <Text>交易日：{status.trade_date ?? "-"}</Text>
              </Space>
              <Progress percent={pct} status={status.state === "error" ? "exception" : running ? "active" : "normal"} />
              <Space size="large">
                <Text>总计 {status.total}</Text>
                <Text type="success">成功 {status.ok}</Text>
                <Text type="danger">失败 {status.failed}</Text>
              </Space>
              {status.error && <Text type="danger">错误：{status.error}</Text>}
            </div>
          )}
        </Space>
      </Card>

      <Card title="自选股筹码补全">
        <Space direction="vertical" size="middle" style={{ width: "100%" }}>
          <div>
            <Text type="secondary">
              对所有自选股重新拉取日K并全量重算筹码分布，补齐因停机/漏采缺失的历史日期。
              一次运行会把每只自选股全部已有日K对应的日期筹码刷新补齐。
            </Text>
          </div>
          <Space>
            <Select
              value={window}
              onChange={setWindow}
              style={{ width: 140 }}
              options={[
                { value: "120", label: "最近 120 天" },
                { value: "365", label: "最近 365 天" },
                { value: "all", label: "全部（~1000 天）" },
              ]}
            />
            <Button
              type="primary"
              loading={backfillLoading}
              onClick={triggerBackfill}
              disabled={backfillRunning}
            >
              {backfillRunning ? "补全中…" : "开始补全"}
            </Button>
          </Space>
          {backfillStatus && backfillStatus.state && (
            <div>
              <Space>
                <Tag color={backfillStatus.state === "done" ? "green" : backfillStatus.state === "error" ? "red" : "blue"}>
                  {backfillStatus.state}
                </Tag>
                <Text>窗口：{backfillStatus.window ?? "-"}</Text>
              </Space>
              <Progress
                percent={backfillPct}
                status={backfillStatus.state === "error" ? "exception" : backfillRunning ? "active" : "normal"}
              />
              <Space size="large">
                <Text>总计 {backfillStatus.total}</Text>
                <Text type="success">成功 {backfillStatus.ok}</Text>
                <Text type="danger">失败 {backfillStatus.failed}</Text>
              </Space>
              {backfillStatus.error && <Text type="danger">错误：{backfillStatus.error}</Text>}
            </div>
          )}
        </Space>
      </Card>
    </Space>
  );
}
```

- [ ] **Step 2: 构建验证**

Run: `cd frontend && npm run build`
Expected: 构建成功，无 TS 错误

- [ ] **Step 3: 提交**

```bash
git -C D:/Codes/ChipScope add frontend/src/pages/ArchivePage.tsx
git -C D:/Codes/ChipScope commit -m "feat(chip-backfill): 数据存档页加「自选股筹码补全」Card"
```

---

### Task 7: 收尾 — 全量测试 + README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: 全量后端测试**

Run: `cd backend && .venv/Scripts/python -m pytest`
Expected: 全绿（原有测试 + 新增 test_chip_backfill 6 个 + test_archive_api 新增 4 个）

- [ ] **Step 2: 前端构建 + lint**

Run: `cd frontend && npm run lint && npm run build`
Expected: 通过

- [ ] **Step 3: 更新 README**

在 `README.md` 核心功能表的「分时存档」行之后加一行：

```markdown
| 自选股筹码补全 | 一键对所有自选股全量重算筹码，补齐停机/漏采缺失的历史日期（按钮手动触发，可选 120/365/全部窗口） | ✅ |
```

在 API 表的 `GET /api/archive/minute/status` 行之后加两行：

```markdown
| POST | `/api/archive/chip-backfill?days=` | 触发自选股筹码补全（异步后台，202；运行中 409；非法窗口 422） |
| GET | `/api/archive/chip-backfill/status` | 补全任务状态（state/window/total/done/ok/failed），前端轮询进度 |
```

在开发路线的「每日全市场分时存档（已完成）」项之后加一项：

```markdown
- **自选股筹码补全（已完成）**：数据存档页加按钮，一键对所有自选股全量重算筹码补齐缺失日期（窗口可选 120/365/全部）。复用 ingest_kline_and_chips 编排 + 存档页按钮/进度模式。spec `docs/superpowers/specs/2026-06-22-watchlist-chip-backfill-design.md`，plan `docs/superpowers/plans/2026-06-22-watchlist-chip-backfill.md`
```

- [ ] **Step 4: 提交**

```bash
git -C D:/Codes/ChipScope add README.md
git -C D:/Codes/ChipScope commit -m "docs: README 补自选股筹码补全"
```

---

## 完成后

- 走 `superpowers:finishing-a-development-branch`：先确认全量测试绿，再选合并/PR/保留分支。
- 更新 memory `chipscope-status.md`：追加「自选股筹码补全（已完成）」条目。
