from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

_CST = ZoneInfo("Asia/Shanghai")
UTC = timezone.utc


def trading_day_ts(date_str: str) -> datetime:
    """交易日字符串 '2026-06-13' → 该日 15:30 北京时间的 UTC-aware datetime。

    收盘时刻固定取 15:30，作为该交易日在 daily_kline 中的 ts。
    """
    d = datetime.strptime(date_str, "%Y-%m-%d").date()
    local = datetime.combine(d, time(15, 30), tzinfo=_CST)
    return local.astimezone(UTC)
