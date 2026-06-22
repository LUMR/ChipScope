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

    valid_count = valid.sum(axis=0)             # (240,) 每时刻有效股数
    with np.errstate(all="ignore"):
        sum_pct = np.nansum(mat, axis=0)        # (240,)；全 NaN 列 nansum=0
        # 0/0 → nan（valid_count=0 的列），errstate 抑制 invalid-divide 警告
        avg = np.where(valid_count > 0, sum_pct / valid_count, np.nan)

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
