"""盯盘告警评估引擎：条件 DSL、指标上下文构建、规则评估与触发。

条件 DSL（JSONB 数组，AND 语义）::

    {"scope": "realtime", "metric": "pct_change",   "op": "gte", "value": 5.0}
    {"scope": "chip",     "metric": "profit_ratio", "op": "cross_above", "value": 0.8}
    {"scope": "pattern",  "metric": "pattern",      "op": "eq", "value": "single_peak_dense"}

- realtime 规则在 realtime_loop（3s tick）评估，需自带交易时段闸门（scheduler 侧）
- chip/pattern 规则在 16:20 日级 job 评估，trade_date 去重
- cross_* 为边沿触发：realtime 前值来自引擎内 EdgeState（上一 tick），chip 前值来自
  DB 倒数第二行快照，评估上下文统一以 "prev:metric" 键提供
"""
import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select, update

from app.config import get_settings
from app.models.alert import AlertEvent, AlertRule
from app.models.chip import ChipDistribution
from app.models.kline import DailyKline
from app.models.stock import StockMeta
from app.services.chip_pattern import recognize, recognize_trend
from app.services.notify import WecomWebhook, render_alert_markdown

_CST = ZoneInfo("Asia/Shanghai")

# ---------------------------------------------------------------------------
# metric 注册表（供条件校验、GET /api/alerts/metrics 下拉、消息渲染共用）
# ---------------------------------------------------------------------------

_NUM_OPS = ("gt", "lt", "gte", "lte", "cross_above", "cross_below")
_ENUM_OPS = ("eq", "ne")

OP_LABELS = {
    "gt": ">",
    "lt": "<",
    "gte": "≥",
    "lte": "≤",
    "cross_above": "上穿",
    "cross_below": "下穿",
    "eq": "=",
    "ne": "≠",
}

# 条件 DSL 枚举取值：(英文 key, 中文形态名)
PATTERN_OPTIONS = (
    ("single_peak_dense", "单峰密集"),
    ("high_single_peak", "高位单峰"),
    ("low_single_peak", "低位单峰"),
    ("divergent", "筹码发散"),
    ("none", "无明显形态"),
)
TREND_OPTIONS = (
    ("cost_up", "筹码上移"),
    ("cost_down", "筹码下移"),
    ("none", "无明显形态"),
)
# chip_pattern 返回中文形态名 → 条件 DSL 英文 key
PATTERN_KEYS = {label: key for key, label in PATTERN_OPTIONS}
TREND_KEYS = {label: key for key, label in TREND_OPTIONS}


@dataclass(frozen=True)
class MetricDef:
    scope: str  # realtime / chip / pattern
    metric: str
    label: str
    ops: tuple[str, ...]
    options: tuple[tuple[str, str], ...] = ()  # enum 取值 (key, 中文)；空 = 数值

    @property
    def is_enum(self) -> bool:
        return bool(self.options)


METRICS: tuple[MetricDef, ...] = (
    MetricDef("realtime", "price", "现价(元)", _NUM_OPS),
    MetricDef("realtime", "open", "今开(元)", _NUM_OPS),
    MetricDef("realtime", "high", "最高(元)", _NUM_OPS),
    MetricDef("realtime", "low", "最低(元)", _NUM_OPS),
    MetricDef("realtime", "pct_change", "涨跌幅(%)", _NUM_OPS),
    MetricDef("realtime", "vol", "成交量(手)", _NUM_OPS),
    MetricDef("realtime", "amount", "成交额(元)", _NUM_OPS),
    MetricDef("chip", "profit_ratio", "获利盘(0-1)", _NUM_OPS),
    MetricDef("chip", "concentration", "90%集中度(0-1)", _NUM_OPS),
    MetricDef("chip", "avg_cost", "平均成本(元)", _NUM_OPS),
    MetricDef("chip", "cost_high", "成本上沿(元)", _NUM_OPS),
    MetricDef("chip", "cost_low", "成本下沿(元)", _NUM_OPS),
    MetricDef("pattern", "pattern", "筹码形态", _ENUM_OPS, PATTERN_OPTIONS),
    MetricDef("pattern", "trend", "筹码趋势", _ENUM_OPS, TREND_OPTIONS),
)

METRIC_INDEX: dict[tuple[str, str], MetricDef] = {
    (m.scope, m.metric): m for m in METRICS
}

# 消息展示用的样例值（POST /api/alerts/rules/{id}/test 渲染样例消息）
_SAMPLE_VALUES: dict = {
    "price": 1689.0, "open": 1670.0, "high": 1698.0, "low": 1665.0,
    "pct_change": 5.23, "vol": 32500.0, "amount": 5_500_000_000.0,
    "profit_ratio": 0.85, "concentration": 0.12,
    "avg_cost": 1605.0, "cost_high": 1750.0, "cost_low": 1520.0,
    "pattern": "single_peak_dense", "pattern_label": "单峰密集",
    "trend": "cost_up", "trend_label": "筹码上移",
}


# ---------------------------------------------------------------------------
# 纯函数（无 I/O，直接单测）
# ---------------------------------------------------------------------------

def in_trading_window(now: datetime) -> bool:
    """周一~五 09:15-11:35 / 12:55-15:05（北京时间，带集合竞价/收盘缓冲）。

    节假日不识别（已知限制）。now 需为 aware datetime。
    """
    cst = now.astimezone(_CST)
    if cst.weekday() >= 5:  # 周六/周日
        return False
    m = cst.hour * 60 + cst.minute
    return 9 * 60 + 15 <= m <= 11 * 60 + 35 or 12 * 60 + 55 <= m <= 15 * 60 + 5


def build_realtime_values(quote) -> dict:
    """RealtimeQuote → 评估上下文（pct_change 现算；last_close=0 时为 None）。"""
    pct_change = (
        (quote.price - quote.last_close) / quote.last_close * 100
        if quote.last_close
        else None
    )
    return {
        "price": quote.price,
        "open": quote.open,
        "high": quote.high,
        "low": quote.low,
        "pct_change": pct_change,
        "vol": quote.vol,
        "amount": quote.amount,
    }


def build_daily_values(chips: list, current_price: float | None) -> dict:
    """chip 快照序列（ts 降序，≥1 行）→ 日级评估上下文。

    chip 列取最新行；pattern/trend 用 chip_pattern 纯函数现算；
    "prev:*" 为次新快照的 chip 列（cross_* 边沿检测前值）。
    current_price 缺失（无日K）时 pattern 置 None，形态条件不触发。
    """
    latest = chips[0]
    dist = latest.distribution or {}
    peak_ratio = max(dist.values()) if dist else 0.0
    peak_price = float(max(dist, key=dist.get)) if dist else 0.0
    pattern = recognize(
        float(latest.concentration), peak_price, peak_ratio, current_price or 0.0
    )
    trend = recognize_trend([float(r.avg_cost) for r in reversed(chips)])
    values = {
        "profit_ratio": float(latest.profit_ratio),
        "concentration": float(latest.concentration),
        "avg_cost": float(latest.avg_cost),
        "cost_high": float(latest.cost_high),
        "cost_low": float(latest.cost_low),
        "pattern": (
            PATTERN_KEYS.get(pattern["name"], "none")
            if current_price is not None
            else None
        ),
        "pattern_label": pattern["name"] if current_price is not None else "",
        "trend": TREND_KEYS.get(trend["name"], "none"),
        "trend_label": trend["name"],
    }
    if len(chips) >= 2:
        prev = chips[1]
        for col in ("profit_ratio", "concentration", "avg_cost", "cost_high", "cost_low"):
            values[f"prev:{col}"] = float(getattr(prev, col))
    return values


def evaluate_conditions(conditions: list[dict], values: dict) -> bool:
    """AND 语义逐条评估。坏条件（未知 metric/op、缺值、类型不符、脏数据转数值失败）
    记日志并整体判 False，防止单条脏数据打断 realtime_loop。"""
    for cond in conditions:
        try:
            if not _check_condition(cond, values):
                return False
        except (KeyError, TypeError, ValueError) as e:
            print(f"[alert] 坏条件，规则判 False：{cond}（{e}）")
            return False
    return True


def _check_condition(cond: dict, values: dict) -> bool:
    m = METRIC_INDEX.get((cond.get("scope"), cond.get("metric")))
    if m is None:
        raise KeyError(f"unknown metric {cond.get('scope')}.{cond.get('metric')}")
    op = cond.get("op")
    if op not in m.ops:
        raise KeyError(f"op {op} not allowed for {m.scope}.{m.metric}")
    cur = values[cond["metric"]]  # 缺值（None/键不存在）→ KeyError/None
    if cur is None:
        return False
    value = cond.get("value")
    if m.is_enum:
        return (cur == value) if op == "eq" else (cur != value)
    cur = float(cur)
    value = float(value)
    if op == "gt":
        return cur > value
    if op == "lt":
        return cur < value
    if op == "gte":
        return cur >= value
    if op == "lte":
        return cur <= value
    prev = values.get(f"prev:{cond['metric']}")
    if prev is None:  # 无前值不判边沿
        return False
    prev = float(prev)
    if op == "cross_above":
        return cur > value and prev <= value
    return cur < value and prev >= value  # cross_below


def describe_rule(conditions: list[dict]) -> str:
    """条件数组 → 中文描述："涨跌幅(%) ≥ 5 且 成交额(元) > 1000000000"。"""
    parts = []
    for cond in conditions:
        m = METRIC_INDEX.get((cond.get("scope"), cond.get("metric")))
        label = m.label if m else str(cond.get("metric"))
        op = OP_LABELS.get(cond.get("op"), str(cond.get("op")))
        value = cond.get("value")
        if m is not None and m.is_enum:
            value = dict(m.options).get(value, value)
        parts.append(f"{label} {op} {value}")
    return " 且 ".join(parts)


def rule_kind(conditions: list[dict]) -> str | None:
    """规则分组：全 realtime → 'realtime'；全 ∈ {chip, pattern} → 'daily'。

    混用 realtime 与日级 scope、或含未知 scope → None（不评估）。供引擎
    分流与 API 校验（混用 422）共用。
    """
    if not conditions:
        return None
    scopes = {c.get("scope") for c in conditions}
    if not scopes or not scopes <= {"realtime", "chip", "pattern"}:
        return None
    if scopes == {"realtime"}:
        return "realtime"
    if scopes <= {"chip", "pattern"}:
        return "daily"
    return None


def _fmt_value(metric: str, v) -> str:
    if v is None:
        return "—"
    if not isinstance(v, (int, float)):
        return str(v)
    if metric == "pct_change":
        return f"{v:+.2f}%"
    if metric in ("profit_ratio", "concentration"):
        return f"{v:.2%}"
    if metric == "vol" or abs(v) >= 10000:
        return f"{v:,.0f}"
    return f"{v:,.2f}"


def display_values(conditions: list[dict], values: dict) -> dict[str, str]:
    """挑出条件引用的 metric → 「中文标签 → 格式化现值」（通知"现值"行）。

    pct_change 自动附带现价；pattern/trend 用中文形态名。
    """
    keys: list[str] = []
    for c in conditions:
        m = c.get("metric")
        if m in values and m not in keys:
            keys.append(m)
    if "pct_change" in keys and "price" in values and "price" not in keys:
        keys.append("price")
    out: dict[str, str] = {}
    for k in keys:
        scope = next((c.get("scope") for c in conditions if c.get("metric") == k), "")
        m = METRIC_INDEX.get((scope, k))
        label = m.label if m else k
        v = (
            values.get(f"{k}_label", values.get(k))
            if k in ("pattern", "trend")
            else values.get(k)
        )
        out[label] = _fmt_value(k, v)
    return out


def sample_values() -> dict:
    """POST /rules/{id}/test 渲染样例消息用的演示值。"""
    return dict(_SAMPLE_VALUES)


@dataclass
class EdgeState:
    """realtime cross_* 边沿检测状态：secucode → 上一 tick 的数值指标。

    模块级单例跨 tick 保留；评估在先（context 注入 prev:*）、更新在后（snapshot）。
    """

    prev: dict[str, dict[str, float]] = field(default_factory=dict)

    def context(self, secucode: str) -> dict:
        return {f"prev:{k}": v for k, v in self.prev.get(secucode, {}).items()}

    def snapshot(self, secucode: str, values: dict) -> None:
        # 只存当 tick 指标：values 里已合并的 "prev:*" 键必须剔除，
        # 否则下轮 context() 再包一层 prev: 逐 tick 无限嵌套（长驻进程泄漏）
        self.prev[secucode] = {
            k: v
            for k, v in values.items()
            if not k.startswith("prev:")
            and isinstance(v, (int, float))
            and not isinstance(v, bool)
        }


edge_state = EdgeState()  # scheduler realtime_loop 用模块级单例


# ---------------------------------------------------------------------------
# 编排（session_factory 可注入，照抄 read_watchlist_secucodes 模式）
# ---------------------------------------------------------------------------

async def load_active_rules(session_factory) -> tuple[list[AlertRule], dict[str, str]]:
    """读全部 enabled 规则 + 涉及股票的 secucode→名称映射（供事件快照）。"""
    async with session_factory() as session:
        rules = (
            (await session.execute(select(AlertRule).where(AlertRule.enabled)))
            .scalars()
            .all()
        )
        codes = sorted({c for r in rules for c in (r.secucodes or [])})
        names: dict[str, str] = {}
        if codes:
            rows = (
                await session.execute(
                    select(StockMeta.secucode, StockMeta.name).where(
                        StockMeta.secucode.in_(codes)
                    )
                )
            ).all()
            names = dict(rows)
    return list(rules), names


async def evaluate_realtime(
    session_factory, rules: list[AlertRule], names: dict[str, str],
    secucode: str, quote, state: EdgeState,
) -> None:
    """realtime_loop 每只股票行情到手后调用：评估该股命中的全部 realtime 规则。

    条件不通过零 DB 查询；通过才查 cooldown。交易时段闸门在 scheduler 侧。
    """
    values = {**state.context(secucode), **build_realtime_values(quote)}
    try:
        for rule in rules:
            if secucode not in (rule.secucodes or []):
                continue
            if rule_kind(rule.conditions) != "realtime":
                continue
            if not evaluate_conditions(rule.conditions, values):
                continue
            if await _cooldown_blocked(session_factory, rule, secucode):
                continue
            await _fire(session_factory, rule, secucode, names.get(secucode, ""), values)
    finally:
        state.snapshot(secucode, values)


async def evaluate_daily(session_factory) -> int:
    """16:20 日级评估：chip/pattern 条件。trade_date 去重，每 (rule, stock, 日) 至多一触。

    仅评估快照新鲜的股票（最新筹码快照的 CST 日期 = 当天）：停牌/当日采集
    失败的旧快照直接跳过，防止按过期值触发、并把旧日期写进去重键导致规则
    锁死。单股异常隔离（rollback 后继续下一只）。返回触发的事件数。
    """
    rules, names = await load_active_rules(session_factory)
    daily_rules = [r for r in rules if rule_kind(r.conditions) == "daily"]
    if not daily_rules:
        return 0
    codes = sorted({c for r in daily_rules for c in (r.secucodes or [])})
    today = datetime.now(timezone.utc).astimezone(_CST).date()
    fired = 0
    async with session_factory() as session:
        for secucode in codes:
            try:
                close = (
                    await session.execute(
                        select(DailyKline.close)
                        .where(DailyKline.secucode == secucode)
                        .order_by(DailyKline.ts.desc())
                        .limit(1)
                    )
                ).scalar_one_or_none()
                chips = (
                    (
                        await session.execute(
                            select(ChipDistribution)
                            .where(ChipDistribution.secucode == secucode)
                            .order_by(ChipDistribution.ts.desc())
                            .limit(30)
                        )
                    )
                    .scalars()
                    .all()
                )
                if not chips:
                    continue
                trade_date = chips[0].ts.astimezone(_CST).date()
                if trade_date != today:
                    print(f"[daily_alerts] {secucode} 快照过期({trade_date})，跳过")
                    continue
                values = build_daily_values(
                    list(chips), float(close) if close is not None else None
                )
                for rule in daily_rules:
                    if secucode not in (rule.secucodes or []):
                        continue
                    if not evaluate_conditions(rule.conditions, values):
                        continue
                    if await _fired_today(session, rule, secucode, trade_date):
                        continue
                    await _fire(
                        session_factory, rule, secucode,
                        names.get(secucode, ""), values, trade_date=trade_date,
                    )
                    fired += 1
            except Exception as e:  # 单股失败（脏数据/坏行使 session 失效）不中断其余
                print(f"[daily_alerts] {secucode} error: {e}")
                await session.rollback()
    return fired


async def _cooldown_blocked(session_factory, rule: AlertRule, secucode: str) -> bool:
    """realtime 冷却：该 (rule, stock) 最近一次触发距今不足 cooldown_minutes。"""
    async with session_factory() as session:
        last = (
            await session.execute(
                select(AlertEvent.triggered_at)
                .where(AlertEvent.rule_id == rule.id, AlertEvent.secucode == secucode)
                .order_by(AlertEvent.triggered_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
    if last is None:
        return False
    now = datetime.now(timezone.utc)
    return last > now - timedelta(minutes=rule.cooldown_minutes)


async def _fired_today(session, rule: AlertRule, secucode: str, trade_date) -> bool:
    """日级去重：该 (rule, stock, trade_date) 已有事件（任意状态）。"""
    hit = (
        await session.execute(
            select(AlertEvent.id)
            .where(
                AlertEvent.rule_id == rule.id,
                AlertEvent.secucode == secucode,
                AlertEvent.trade_date == trade_date,
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    return hit is not None


# 后台发送 task 引用集合：持有以防 GC，task 完成后自动移除（照抄 api/watchlist 模式）
_background_tasks: set[asyncio.Task] = set()


async def _fire(
    session_factory, rule: AlertRule, secucode: str, stock_name: str,
    values: dict, trade_date=None,
) -> None:
    """触发：先落 pending 事件占位（天然防止发送期间重复触发），再后台发送。"""
    now = datetime.now(timezone.utc)
    message = render_alert_markdown(
        rule_name=rule.name,
        stock_name=stock_name,
        secucode=secucode,
        cond_desc=describe_rule(rule.conditions),
        values=display_values(rule.conditions, values),
        triggered_at=now,
        link_base=get_settings().alert_link_base,
    )
    async with session_factory() as session:
        event = AlertEvent(
            rule_id=rule.id,
            rule_name=rule.name,
            stock_name=stock_name,
            secucode=secucode,
            triggered_at=now,
            trade_date=trade_date,
            status="pending",
            payload=values,
            message=message,
        )
        session.add(event)
        await session.commit()
        event_id = event.id
    webhook = rule.webhook_url or get_settings().alert_webhook_url
    task = asyncio.create_task(
        _send_and_update(session_factory, event_id, webhook, message)
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def _send_and_update(
    session_factory, event_id: int, webhook_url: str | None, message: str
) -> None:
    """后台发送并回写状态：成功 sent / 失败 failed / 未配 webhook skipped。

    请求级 session 已关（realtime_loop 路径本就无 session），自建 SessionLocal。
    """
    try:
        if not webhook_url:
            status, detail = "skipped", "未配置 webhook（规则或 CHIPSCOPE_ALERT_WEBHOOK_URL）"
        else:
            await WecomWebhook(webhook_url).send_markdown(message)
            status, detail = "sent", None
    except Exception as e:
        status, detail = "failed", str(e)
    async with session_factory() as session:
        await session.execute(
            update(AlertEvent)
            .where(AlertEvent.id == event_id)
            .values(status=status, detail=detail)
        )
        await session.commit()
