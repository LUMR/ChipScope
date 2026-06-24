"""全市场分时行情存档：A 股清单刷新 + 分时采集 + upsert + 内存状态。"""
from datetime import date

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from app.models.minute_quote import MinuteQuote
from app.services.collector.tdx_client import TdxClient
from app.services.collector.types import KlineBar, StockInfo
from app.services.ingest import upsert_stock_meta

# A 股 code 前缀
_SH_PREFIXES = {"600", "601", "603", "605", "688", "689"}
_SZ_PREFIXES = {"000", "001", "002", "003", "300", "301"}


def prev_close_from_bars(bars: list[KlineBar], trade_date_iso: str) -> float | None:
    """日K中 < trade_date_iso 的最近一根 close = 目标日前一交易日收盘（即前收）。

    取 date 最大者，不依赖 bars 顺序；无候选返回 None。用于历史日分时存档的前收盘价
    （stocks() 只给今天的昨收，历史日须用日K推算）。
    """
    prev = [b for b in bars if b.date < trade_date_iso]
    if not prev:
        return None
    return max(prev, key=lambda b: b.date).close


def _filter_a_shares(df, market: int) -> list[StockInfo]:
    """mootdx stocks() DataFrame + market → 仅沪深 A 股的 StockInfo 列表。

    market=1 沪（SH），market=0 深（SZ）。过滤掉指数/债券/基金/ETF 等。
    """
    if df is None or len(df) == 0:
        return []
    prefixes = _SH_PREFIXES if market == 1 else _SZ_PREFIXES
    suffix = "SH" if market == 1 else "SZ"
    secid_pfx = "1" if market == 1 else "0"
    out: list[StockInfo] = []
    for _, row in df.iterrows():
        code = str(row["code"]).zfill(6)
        if code[:3] in prefixes:
            # mootdx name 含尾部 NULL 字节填充（定长字段），须清理，否则 PG UTF8 列拒收
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


# ---- 进程内状态（单进程模式：API 与 cron 同进程可见）----
_archive_running: bool = False
_archive_status: dict | None = None


def get_archive_status() -> dict | None:
    return _archive_status


def is_archive_running() -> bool:
    return _archive_running


def set_archive_running(value: bool) -> None:
    global _archive_running
    _archive_running = value


def set_archive_status(value: dict | None) -> None:
    global _archive_status
    _archive_status = value


def reset_archive_state() -> None:
    """测试用：清理模块级状态。"""
    global _archive_running, _archive_status
    _archive_running = False
    _archive_status = None


async def archive_minute_quotes(
    session_factory: async_sessionmaker[AsyncSession],
    tdx: TdxClient,
    trade_date,
    on_progress=None,
) -> dict:
    """全市场分时采集主流程：刷新清单 → 遍历每只 → upsert；单只失败计入 failed。

    on_progress(done, total, failed) 每只调用一次。返回 {trade_date, total, ok, failed}。
    """
    stocks = await refresh_stock_universe(session_factory, tdx)
    total = len(stocks)
    ok = 0
    failed = 0
    today = _today_cst()
    date_arg = None if trade_date == today else trade_date.strftime("%Y%m%d")
    trade_iso = trade_date.isoformat()
    for i, s in enumerate(stocks, 1):
        try:
            points = await tdx.minute_time(s.code, date_arg)
            if points:
                # pre_close 统一用日K前一交易日收盘：stocks() 的昨收对除权/陈旧股不可靠
                bars = await tdx.daily_bars(s.code, count=120)
                pre_close = prev_close_from_bars(bars, trade_iso)
                async with session_factory() as session:
                    await upsert_minute_quote(
                        session, trade_date, s.secucode, points, pre_close
                    )
                ok += 1
            else:
                failed += 1
        except Exception as e:  # 单只失败不影响其他
            print(f"[archive] {s.secucode} error: {e}")
            failed += 1
        if on_progress is not None:
            on_progress(i, total, failed)
    return {
        "trade_date": trade_date.strftime("%Y-%m-%d"),
        "total": total,
        "ok": ok,
        "failed": failed,
    }


def _today_cst():
    from zoneinfo import ZoneInfo
    from datetime import datetime
    return datetime.now(ZoneInfo("Asia/Shanghai")).date()
