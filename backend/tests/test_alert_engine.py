"""告警引擎纯函数测试：DSL 构建、各 op 判断、pattern 映射、时段闸门、描述渲染。"""
from datetime import datetime, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from app.services.alert_engine import (
    EdgeState,
    build_daily_values,
    build_realtime_values,
    describe_rule,
    evaluate_conditions,
    in_trading_window,
    rule_kind,
)
from app.services.collector.tdx_client import RealtimeQuote

_CST = ZoneInfo("Asia/Shanghai")


def _quote(price=10.0, last_close=10.0, **kw):
    return RealtimeQuote(
        secucode="600519.SH",
        price=price,
        open=kw.get("open", price),
        last_close=last_close,
        high=kw.get("high", price),
        low=kw.get("low", price),
        vol=kw.get("vol", 1000.0),
        amount=kw.get("amount", 2_000_000.0),
        bids=[],
        asks=[],
    )


def _chip(avg=10.0, conc=0.12, profit=0.8, dist=None):
    return SimpleNamespace(
        distribution=dist if dist is not None else {"10.0": 0.5, "10.2": 0.5},
        concentration=conc,
        profit_ratio=profit,
        avg_cost=avg,
        cost_high=11.0,
        cost_low=9.0,
    )


def _cond(scope, metric, op, value):
    return {"scope": scope, "metric": metric, "op": op, "value": value}


# ---------------------------------------------------------------- build_realtime_values

def test_build_realtime_values_computes_pct_change():
    v = build_realtime_values(_quote(price=10.5, last_close=10.0))
    assert v["price"] == 10.5
    assert v["pct_change"] == 5.0
    assert v["vol"] == 1000.0
    assert v["amount"] == 2_000_000.0


def test_build_realtime_values_pct_change_none_when_no_last_close():
    v = build_realtime_values(_quote(price=10.5, last_close=0.0))
    assert v["pct_change"] is None
    # None 值条件不触发
    assert not evaluate_conditions(
        [_cond("realtime", "pct_change", "gte", 0)], v
    )


# ---------------------------------------------------------------- 各 op 电平/边沿判断

def test_level_ops():
    v = {"price": 10.0}
    assert evaluate_conditions([_cond("realtime", "price", "gt", 9.9)], v)
    assert not evaluate_conditions([_cond("realtime", "price", "gt", 10.0)], v)
    assert evaluate_conditions([_cond("realtime", "price", "gte", 10.0)], v)
    assert evaluate_conditions([_cond("realtime", "price", "lt", 10.1)], v)
    assert evaluate_conditions([_cond("realtime", "price", "lte", 10.0)], v)
    assert not evaluate_conditions([_cond("realtime", "price", "lte", 9.99)], v)


def test_and_semantics():
    conds = [
        _cond("realtime", "pct_change", "gte", 5),
        _cond("realtime", "amount", "gt", 1_000_000),
    ]
    assert evaluate_conditions(conds, {"pct_change": 5.2, "amount": 2e6})
    assert not evaluate_conditions(conds, {"pct_change": 5.2, "amount": 1e5})


def test_cross_above_requires_prev_and_edge():
    cond = _cond("realtime", "price", "cross_above", 10.5)
    assert evaluate_conditions([cond], {"price": 11.0, "prev:price": 10.0})  # 上穿
    assert not evaluate_conditions([cond], {"price": 11.0})  # 无前值不判边沿
    assert not evaluate_conditions([cond], {"price": 11.0, "prev:price": 11.0})  # 一直在上方
    assert not evaluate_conditions([cond], {"price": 10.4, "prev:price": 10.0})  # 未越过阈值


def test_cross_below():
    cond = _cond("realtime", "price", "cross_below", 10.5)
    assert evaluate_conditions([cond], {"price": 10.0, "prev:price": 11.0})
    assert not evaluate_conditions([cond], {"price": 10.0, "prev:price": 10.4})


def test_enum_eq_ne():
    assert evaluate_conditions(
        [_cond("pattern", "pattern", "eq", "single_peak_dense")], {"pattern": "single_peak_dense"}
    )
    assert not evaluate_conditions(
        [_cond("pattern", "pattern", "eq", "divergent")], {"pattern": "single_peak_dense"}
    )
    assert evaluate_conditions(
        [_cond("pattern", "trend", "ne", "none")], {"trend": "cost_up"}
    )


def test_bad_conditions_evaluate_false_not_raise():
    assert not evaluate_conditions([_cond("realtime", "nope", "gt", 1)], {"price": 10})
    assert not evaluate_conditions([_cond("realtime", "price", "between", 1)], {"price": 10})
    assert not evaluate_conditions([_cond("pattern", "pattern", "gt", 1)], {"pattern": "none"})
    # metric 不在上下文中（数据缺失）也判 False
    assert not evaluate_conditions([_cond("chip", "avg_cost", "gt", 1)], {})
    # 脏数据：数值阈值存成非数字字符串 → float() ValueError 同样整体判 False
    assert not evaluate_conditions([_cond("realtime", "price", "gt", "abc")], {"price": 10})


# ---------------------------------------------------------------- build_daily_values

def test_build_daily_values_chip_columns_and_prev():
    chips = [_chip(profit=0.85, avg=10.0), _chip(profit=0.70, avg=9.5)]
    v = build_daily_values(chips, current_price=10.0)
    assert v["profit_ratio"] == 0.85
    assert v["avg_cost"] == 10.0
    assert v["prev:profit_ratio"] == 0.70
    assert v["prev:avg_cost"] == 9.5
    assert v["pattern"] == "single_peak_dense"  # conc 0.12 + peak_ratio 0.5 + 现价居峰内
    assert v["pattern_label"] == "单峰密集"


def test_build_daily_values_pattern_variants():
    # conc>0.30 → 筹码发散
    v = build_daily_values([_chip(conc=0.35)], current_price=10.0)
    assert v["pattern"] == "divergent"
    # 不密集也不发散 → none
    v = build_daily_values([_chip(conc=0.20)], current_price=10.0)
    assert v["pattern"] == "none"
    # 高位/低位单峰
    v = build_daily_values([_chip()], current_price=11.0)  # 峰 10.0×1.05=10.5
    assert v["pattern"] == "high_single_peak"
    v = build_daily_values([_chip()], current_price=9.0)  # 峰 10.0×0.95=9.5
    assert v["pattern"] == "low_single_peak"


def test_build_daily_values_trend_and_no_price():
    # chips 为 ts 降序（最新在前）：近 5 日 avg_cost 时间正序单调升 → cost_up
    chips = [_chip(avg=a) for a in (6.4, 6.3, 6.2, 6.1, 6.0)]
    v = build_daily_values(chips, current_price=10.0)
    assert v["trend"] == "cost_up"
    assert v["trend_label"] == "筹码上移"
    # 时间正序单调降 → cost_down
    chips = [_chip(avg=a) for a in (6.0, 6.1, 6.2, 6.3, 6.4)]
    assert build_daily_values(chips, 10.0)["trend"] == "cost_down"
    # 现价缺失 → pattern None，形态条件不触发
    v = build_daily_values([_chip()], current_price=None)
    assert v["pattern"] is None
    assert not evaluate_conditions(
        [_cond("pattern", "pattern", "eq", "single_peak_dense")], v
    )


def test_chip_cross_uses_prev_snapshot():
    cond = _cond("chip", "profit_ratio", "cross_above", 0.8)
    chips = [_chip(profit=0.85), _chip(profit=0.75)]
    v = build_daily_values(chips, current_price=10.0)
    assert evaluate_conditions([cond], v)
    chips = [_chip(profit=0.85), _chip(profit=0.90)]  # 一直在 0.8 上方
    v = build_daily_values(chips, current_price=10.0)
    assert not evaluate_conditions([cond], v)


# ---------------------------------------------------------------- in_trading_window

def _cst(hh, mm):
    """2026-08-20 为周四，构造该日指定时刻（北京时间）。"""
    return datetime(2026, 8, 20, hh, mm, tzinfo=_CST)


def test_in_trading_window_boundaries():
    # 上午 09:15-11:35
    assert not in_trading_window(_cst(9, 14))
    assert in_trading_window(_cst(9, 15))
    assert in_trading_window(_cst(9, 16))
    assert in_trading_window(_cst(11, 35))
    assert not in_trading_window(_cst(11, 36))
    # 午间休市
    assert not in_trading_window(_cst(12, 0))
    # 下午 12:55-15:05
    assert not in_trading_window(_cst(12, 54))
    assert in_trading_window(_cst(12, 55))
    assert in_trading_window(_cst(15, 5))
    assert not in_trading_window(_cst(15, 6))
    # 周末（2026-08-22 周六 / 08-23 周日）
    assert not in_trading_window(datetime(2026, 8, 22, 10, 0, tzinfo=_CST))
    assert not in_trading_window(datetime(2026, 8, 23, 10, 0, tzinfo=_CST))


def test_in_trading_window_accepts_utc_input():
    # 01:16 UTC == 09:16 CST 周四
    assert in_trading_window(datetime(2026, 8, 20, 1, 16, tzinfo=timezone.utc))


# ---------------------------------------------------------------- describe / rule_kind

def test_describe_rule():
    conds = [
        _cond("realtime", "pct_change", "gte", 5),
        _cond("realtime", "amount", "gt", 1_000_000_000),
    ]
    assert describe_rule(conds) == "涨跌幅(%) ≥ 5 且 成交额(元) > 1000000000"
    assert describe_rule([_cond("pattern", "pattern", "eq", "single_peak_dense")]) == (
        "筹码形态 = 单峰密集"
    )


def test_rule_kind_grouping():
    assert rule_kind([_cond("realtime", "price", "gt", 1)]) == "realtime"
    assert rule_kind(
        [_cond("chip", "avg_cost", "gt", 1), _cond("pattern", "trend", "eq", "cost_up")]
    ) == "daily"
    assert rule_kind(
        [_cond("realtime", "price", "gt", 1), _cond("chip", "avg_cost", "gt", 1)]
    ) is None  # 混用
    assert rule_kind([]) is None
    assert rule_kind([_cond("other", "x", "gt", 1)]) is None


# ---------------------------------------------------------------- EdgeState

def test_edge_state_snapshot_and_context():
    st = EdgeState()
    assert st.context("600519.SH") == {}
    st.snapshot("600519.SH", {"price": 10.0, "pct_change": 5.0, "pattern": "none"})
    ctx = st.context("600519.SH")
    assert ctx == {"prev:price": 10.0, "prev:pct_change": 5.0}  # 非数值不存
    # 下一 tick 覆盖
    st.snapshot("600519.SH", {"price": 10.5, "pct_change": 5.5})
    assert st.context("600519.SH") == {"prev:price": 10.5, "prev:pct_change": 5.5}


def test_edge_state_does_not_nest_prev_keys():
    """回归：snapshot 不得把 context 注入的 prev:* 再存回去（逐 tick 无限嵌套）。"""
    st = EdgeState()
    st.snapshot("600519.SH", {"price": 10.0})
    for tick in range(3):
        values = {**st.context("600519.SH"), "price": 10.0 + tick}
        st.snapshot("600519.SH", values)
    # 任意多 tick 后仍只有一层前值
    assert st.context("600519.SH") == {"prev:price": 12.0}
