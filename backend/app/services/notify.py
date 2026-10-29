"""告警通知：企业微信群机器人 markdown webhook。

- `Notifier` Protocol 为多渠道扩展点，`WecomWebhook` 是首个实现
- 传输层错误（网络/超时）指数退避重试；业务错误（errcode != 0）直接抛 NotifyError 不重试
- 模块级节流：串行化发送且间隔 ≥3s（企业微信机器人限 20 条/分钟）
"""
import asyncio
import time
from datetime import datetime
from typing import Protocol
from zoneinfo import ZoneInfo

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

_CST = ZoneInfo("Asia/Shanghai")


class NotifyError(Exception):
    """业务错误（webhook 返回 errcode != 0）：重试无意义。"""


# 传输层重试：指数退避 1s→2s→4s，最多 3 次（仿 collector/retry.py）
_transport_retry = retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    retry=retry_if_exception_type(
        (httpx.TransportError, httpx.RemoteProtocolError, httpx.TimeoutException)
    ),
)


class Notifier(Protocol):
    """通知渠道接口：实现 `send_markdown(content)` 即可接入告警引擎。"""

    async def send_markdown(self, content: str) -> None: ...


# 全局节流：串行化发送且间隔 ≥3s，避免触发企业微信 20 条/分钟限频
_send_lock = asyncio.Lock()
_last_sent = 0.0
_MIN_INTERVAL = 3.0


def reset_throttle() -> None:
    """清零节流状态（测试隔离用）。"""
    global _last_sent
    _last_sent = 0.0


class WecomWebhook:
    """企业微信群机器人 markdown 通知。"""

    def __init__(self, webhook_url: str) -> None:
        self.webhook_url = webhook_url

    async def send_markdown(self, content: str) -> None:
        async with httpx.AsyncClient(timeout=10) as client:
            await self._send(client, content)

    @_transport_retry
    async def _send(self, client: httpx.AsyncClient, content: str) -> None:
        global _last_sent
        async with _send_lock:
            wait = _last_sent + _MIN_INTERVAL - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            _last_sent = time.monotonic()
            resp = await client.post(
                self.webhook_url,  # 完整机器人地址（含 key），不能用常量端点
                json={"msgtype": "markdown", "markdown": {"content": content}},
            )
        data = resp.json()
        if data.get("errcode") != 0:
            raise NotifyError(
                f"wecom errcode={data.get('errcode')} errmsg={data.get('errmsg')}"
            )


def render_alert_markdown(
    rule_name: str,
    stock_name: str,
    secucode: str,
    cond_desc: str,
    values: dict[str, str],
    triggered_at: datetime,
    link_base: str = "",
) -> str:
    """渲染告警 markdown。

    values 为「指标中文标签 → 已格式化现值」映射（由 alert_engine._display_values 构造），
    按插入顺序用 " / " 连接。triggered_at 渲染为北京时间；link_base 为空时省略链接行。
    """
    ts = triggered_at.astimezone(_CST).strftime("%Y-%m-%d %H:%M:%S")
    stock = f"{stock_name}（{secucode}）" if stock_name else secucode
    now_values = " / ".join(f"{k} {v}" for k, v in values.items()) or "—"
    lines = [
        "## <font color=\"warning\">🔔 ChipScope 盯盘告警</font>",
        f"> **规则**：{rule_name}",
        f"> **股票**：{stock}",
        f"> **时间**：{ts}",
        f"> **条件**：{cond_desc}",
        f"> **现值**：<font color=\"warning\">{now_values}</font>",
    ]
    if link_base:
        lines.append(f"> [查看个股]({link_base.rstrip('/')}/stock/{secucode})")
    return "\n".join(lines)
