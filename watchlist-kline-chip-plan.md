# 添加自选股后自动拉取历史 K线 + 筹码分布 — 实现计划

> 状态:**待实现**。本文档为实现计划,代码尚未编写。

## Context（为什么做这个改动）

当前「添加自选股」后前端看不到历史 K线和筹码分布。根因是数据从未被采集:

- `POST /api/watchlist` 的 `add_watchlist`(`backend/app/api/watchlist.py:86`)只做两件事:补 `stock_meta` 元数据 + 往 `watchlist` 表插一行,**全程不采集 K线/筹码**。
- `build_scheduler`(`backend/app/scheduler.py:131`)只有 `realtime_loop`(每 3s 行情)和 `daily_holders_flow`(每日 16:00 股东+资金流),**无 K线/筹码定时任务**。
- `GET /api/stocks/{secucode}/kline` 和 `GET /api/stocks/{secucode}/chips` 都**只读 DB**。
- `ingest_daily_kline` / `compute_chip_series` / `upsert_chip_distribution` 三个现成函数在整个 `app/`(API+scheduler)里**从未被调用**,只在 `scripts/`、`tests/` 里用。

目标:添加自选股后,自动采集该股历史日K → 算出历史筹码分布 → 落库;并新增每日定时任务增量补K线+重算筹码,使图表持续更新。

## 关键设计决策

1. **同步采集(非后台任务)**:`get_db`(`backend/app/api/deps.py:8`)的 session 与请求生命周期绑定,后台 `create_task` 会在请求返回后遭遇 session 已关闭。`add_watchlist` 是低频人工操作,同步等待 1–3s 可接受。**采集失败不得回滚 watchlist**:先 commit watchlist 行,再用 try/except 包裹采集,失败仅 `print` 日志(参照 `scheduler.py:127` 的范式)。
2. **daily 任务遍历 watchlist(非 stock_meta 全表)**:全表可能几千只,每只东财调用 + 0.5s 节流会超出盘后窗口;watchlist 是用户关心的子集,与 `realtime_loop` 语义一致。
3. **K线增量拉取 + 筹码全量重算**:K线用增量 beg(已有 `max(ts)` 次日,首次用 `today - kline_history_days`),`ON CONFLICT DO UPDATE` 幂等。筹码必须重算整段——`compute_chip_series`(`chip_compute.py:11`)逐日衰减依赖完整序列,纯 NumPy 120~250 天毫秒级。
4. **decay_coeff 取最新 `HolderSummary.decay_coeff`,缺省 2.0**:与现有 scripts 全部硬编码 2.0 一致;新股无 holder_summary 时用配置默认值。`daily_holders_flow` 跑过后 holder_summary 即有真实值。

## 文件改动清单

### 1. 新建 `backend/app/services/kline_chip.py`（可复用编排层）

```
async def resolve_decay_coeff(session, secucode) -> float
    # select HolderSummary where secucode order by ts desc limit 1 → .decay_coeff；
    # 无则 get_settings().chip_decay_default

def _cst_today_str() -> str
    # datetime.now(ZoneInfo("Asia/Shanghai")).date() → "%Y%m%d"

async def _load_klines_as_dicts(session, secucode) -> list[dict]
    # select DailyKline where secucode order by ts asc；
    # 转 {"ts","low","high","vwap","volume","turnover_rate","close"}，
    # Numeric 列 float() 显式转换（参照 test_ingest.py 的转换）

async def _compute_beg(session, secucode, default_days) -> str
    # select max(ts)；有则 (该日+1天).strftime("%Y%m%d")，无则 (today-default_days)

async def ingest_kline_and_chips(em, session, secucode, secid, *,
        days: int | None = None) -> dict
    # 1) beg=_compute_beg(session, secucode, days or settings.kline_history_days), end=_cst_today_str()
    # 2) await ingest_daily_kline(em, session, secucode, secid, beg, end)
    # 3) klines = await _load_klines_as_dicts(session, secucode)
    # 4) 若 klines 为空 → return {"klines":0,"chips":0}（新股/停牌边界，避免 min([]) 崩溃）
    # 5) decay = await resolve_decay_coeff(session, secucode)
    # 6) centers, results = compute_chip_series(klines, decay)
    # 7) n = await upsert_chip_distribution(session, secucode, centers, results, decay)
    # 8) return {"klines": len(klines), "chips": n}
```

复用现有函数:`ingest.ingest_daily_kline`、`chip_compute.compute_chip_series` / `upsert_chip_distribution`、`utils.time` 的 CST 范式。

### 2. 修改 `backend/app/config.py`

在 `Settings` 类加两个字段（紧跟 `eastmoney_*` 块或 `watchlist_default` 后，风格一致）:
```
kline_history_days: int = 120      # 首次拉取/daily 兜底天数
chip_decay_default: float = 2.0    # 无 holder_summary 时衰减系数
```
对应 env:`CHIPSCOPE_KLINE_HISTORY_DAYS`、`CHIPSCOPE_CHIP_DECAY_DEFAULT`。

### 3. 修改 `backend/app/api/watchlist.py`

在 `add_watchlist`(`:86`)现有 `await db.commit()`（`:111`）**之后**、构造返回对象**之前**插入采集块。复用已查到的 `exists.secid`（`StockMeta`），不重复查 meta:
```
try:
    async with EastMoneyClient() as em:
        r = await ingest_kline_and_chips(
            em, db, body.secucode, exists.secid,
            days=get_settings().kline_history_days,
        )
    print(f"[watchlist] {body.secucode} ingested: {r}")
except Exception as e:
    print(f"[watchlist] {body.secucode} kline/chip ingest failed: {e}")
```
顶部 import 加 `from app.services.kline_chip import ingest_kline_and_chips`。重复添加（`on_conflict_do_nothing` 命中）仍会触发采集——幂等，可接受（简单正确）。

### 4. 修改 `backend/app/scheduler.py`

新增函数 + 注册。daily 任务需 `(secucode, secid)`,因此 join `stock_meta`:
```
async def daily_kline_chip() -> None:
    """16:05 增量拉 watchlist 自选股日K + 重算筹码。单只 try/except 不影响其他。"""
    async with EastMoneyClient() as em, SessionLocal() as session:
        stmt = (select(Watchlist.secucode, StockMeta.secid)
                .join(StockMeta, Watchlist.secucode == StockMeta.secucode)
                .where(Watchlist.scope == SCOPE))
        rows = (await session.execute(stmt)).all()
        for secucode, secid in rows:
            try:
                r = await ingest_kline_and_chips(
                    em, session, secucode, secid, days=get_settings().kline_history_days)
                print(f"[daily_kline_chip] {secucode}: {r}")
            except Exception as e:
                print(f"[daily_kline_chip] {secucode} error: {e}")
```
`build_scheduler`(`:131`)加:`sched.add_job(daily_kline_chip, CronTrigger(hour=16, minute=5), id="daily_kline_chip")`（**id 不可复用 "daily"**，错开 5 分钟避免与 16:00 holders 任务抢东财节流）。顶部加 import，更新 docstring。

### 5. 新建 `backend/tests/test_kline_chip.py`

复用 `db_session` + `respx_mock` fixture，K线 mock 走 `https://push2his.eastmoney.com/api/qt/stock/kline/get` 返回 `{"data":{"klines":[...]}}`（参照 `test_eastmoney.py:42`）。用例:
- `test_ingest_kline_and_chips_end_to_end`:mock 3 根日K → 断言 `daily_kline`、`chip_distribution` 各 3 行，返回 `{"klines":3,"chips":3}`。
- `test_resolve_decay_uses_holder_when_available`:插 HolderSummary(decay=3.5) → `resolve_decay_coeff` 返回 3.5。
- `test_resolve_decay_defaults_when_no_holder`:无 holder → 返回 `settings.chip_decay_default`（2.0）。
- `test_ingest_empty_kline_skips_chips`:mock `{"data":None}` → 返回 `{"klines":0,"chips":0}`，不抛异常。
- `test_add_watchlist_triggers_ingest`:POST `/api/watchlist` → 断言两张表有数据。
- `test_add_watchlist_ingest_failure_does_not_rollback`:让采集抛异常 → POST 仍 201 且 watchlist 表有该行（验证容错边界）。

## 边界与风险（实现时务必处理）

- **Numeric→float**:`DailyKline` 的 Numeric 列读出是 `Decimal`,喂 NumPy 前必须 `float()`(`_load_klines_as_dicts` 内转换)。
- **空序列**:`compute_chip_series` 的 `min(lows)/max(highs)` 对空列表抛 `ValueError`,日K为空时提前 return(已纳入函数设计)。
- **北京时区算 today**:用 `datetime.now(ZoneInfo("Asia/Shanghai")).date()`,否则跨天少拉/多拉;`max(ts)` 是 UTC aware,比较时用 aware datetime。
- **bin 区间漂移重写历史**:`compute_chip_series` 的 `lo,hi=min(lows)*0.9,max(highs)*1.1` 随新数据变化,每次重算会 upsert 覆盖该 secucode **所有历史** chip_distribution 行(distribution bin 中心变了)。幂等 upsert 能 handle,属算法正确行为,PR 说明里点出,避免被误判为 bug。
- **fetch_daily_kline 无 `@em_retry`**:限流时单只失败被 try/except 吞掉、不影响其他(daily 任务降级,可接受)。本次不给它加 retry(避免改动既有方法契约)。
- **EastMoneyClient 在 add 里构造两次**(`_ensure_stock_meta` 一次 + 采集一次):两次 0.5s 节流仍秒级,本次不改 `_ensure_stock_meta` 签名,保持改动聚焦。

## 验证步骤

1. **单测**:`cd backend && PYTHONPATH=. pytest tests/test_kline_chip.py -v`
2. **回归**:`pytest tests/test_api_watchlist.py tests/test_chip_compute.py tests/test_ingest.py -v`
3. **编排层冒烟**(真连东财):
   ```
   cd backend && PYTHONPATH=. python -c "
   import asyncio
   from app.database import SessionLocal
   from app.services.collector.eastmoney import EastMoneyClient
   from app.services.kline_chip import ingest_kline_and_chips
   async def m():
       async with EastMoneyClient() as em, SessionLocal() as s:
           print(await ingest_kline_and_chips(em, s, '600519.SH', '1.600519', days=30))
   asyncio.run(m())"
   ```
   预期 `{'klines': ~22, 'chips': ~22}`。
4. **API 端到端**:起 `uvicorn app.main:app --port 8001` → `curl -X POST :8001/api/watchlist -d '{"secucode":"600519.SH"}'`(延迟 1–3s 返回 201)→ `curl :8000/api/stocks/600519.SH/kline?limit=5` 与 `/chips`、`/chips/history?limit=5` 应有数据。
5. **daily 任务**:REPL 直接 `asyncio.run(daily_kline_chip())`,看每只自选股采集日志无 error。
6. **DB 抽查**:`SELECT secucode,count(*) FROM daily_kline GROUP BY 1;` 及 `chip_distribution` 同理,确认每只自选股行数 ≥ 20。

## 涉及文件

- 新建 `backend/app/services/kline_chip.py`
- 修改 `backend/app/config.py`、`backend/app/api/watchlist.py`、`backend/app/scheduler.py`
- 新建 `backend/tests/test_kline_chip.py`
