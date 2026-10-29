"""通知服务测试：企业微信 webhook 成功/业务错误/传输重试 + markdown 渲染。"""
from datetime import datetime, timezone

import httpx
import pytest
from app.services.notify import (
    NotifyError,
    WecomWebhook,
    render_alert_markdown,
    reset_throttle,
)

# 完整机器人地址（含 key）。各用例只 mock 这个 URL：若实现退回 POST 硬编码
# 常量端点（key 丢失），请求匹配不到路由会直接失败 —— 回归防护
WEBHOOK_URL = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=secret-key"


@pytest.fixture(autouse=True)
def _no_throttle(monkeypatch):
    """测试不打 3s 发送间隔。"""
    monkeypatch.setattr("app.services.notify._MIN_INTERVAL", 0.0)
    reset_throttle()


@pytest.mark.asyncio
async def test_send_markdown_posts_to_configured_url(respx_mock):
    """必须 POST 到配置的 webhook（含 key），而非硬编码常量端点。"""
    route = respx_mock.post(WEBHOOK_URL).mock(
        return_value=httpx.Response(200, json={"errcode": 0, "errmsg": "ok"})
    )
    await WecomWebhook(WEBHOOK_URL).send_markdown("hello")
    assert route.called
    assert str(route.calls.last.request.url) == WEBHOOK_URL
    body = route.calls.last.request.content
    assert b'"msgtype":"markdown"' in body
    assert b"hello" in body


@pytest.mark.asyncio
async def test_send_markdown_biz_error_no_retry(respx_mock):
    """errcode != 0 属业务错误：直接抛 NotifyError，不重试。"""
    route = respx_mock.post(WEBHOOK_URL).mock(
        return_value=httpx.Response(200, json={"errcode": 93000, "errmsg": "invalid webhook"})
    )
    with pytest.raises(NotifyError, match="93000"):
        await WecomWebhook(WEBHOOK_URL).send_markdown("x")
    assert route.call_count == 1  # 未重试


@pytest.mark.asyncio
async def test_send_markdown_retries_transport_error(respx_mock):
    """传输错误（如连接中断）重试后成功（共 2 次调用）。"""
    route = respx_mock.post(WEBHOOK_URL).mock(
        side_effect=[
            httpx.TransportError("conn reset"),
            httpx.Response(200, json={"errcode": 0, "errmsg": "ok"}),
        ]
    )
    await WecomWebhook(WEBHOOK_URL).send_markdown("x")
    assert route.call_count == 2


@pytest.mark.asyncio
async def test_send_markdown_gives_up_after_3_attempts(respx_mock):
    route = respx_mock.post(WEBHOOK_URL).mock(
        side_effect=httpx.TransportError("down")
    )
    with pytest.raises(httpx.TransportError):
        await WecomWebhook(WEBHOOK_URL).send_markdown("x")
    assert route.call_count == 3


def test_render_markdown_full_template():
    msg = render_alert_markdown(
        rule_name="涨幅超5%",
        stock_name="贵州茅台",
        secucode="600519.SH",
        cond_desc="涨跌幅(%) ≥ 5",
        values={"涨跌幅(%)": "+5.23%", "现价(元)": "1,689.00"},
        triggered_at=datetime(2026, 8, 20, 6, 35, 2, tzinfo=timezone.utc),
        link_base="http://localhost:8001/",
    )
    lines = msg.split("\n")
    assert lines[0] == '## <font color="warning">🔔 ChipScope 盯盘告警</font>'
    assert lines[1] == "> **规则**：涨幅超5%"
    assert lines[2] == "> **股票**：贵州茅台（600519.SH）"
    assert lines[3] == "> **时间**：2026-08-20 14:35:02"  # UTC → CST
    assert lines[4] == "> **条件**：涨跌幅(%) ≥ 5"
    assert lines[5] == (
        '> **现值**：<font color="warning">涨跌幅(%) +5.23% / 现价(元) 1,689.00</font>'
    )
    assert lines[6] == "> [查看个股](http://localhost:8001/stock/600519.SH)"


def test_render_markdown_optional_link_and_name():
    msg = render_alert_markdown(
        rule_name="r",
        stock_name="",
        secucode="000001.SZ",
        cond_desc="c",
        values={"现价(元)": "10.00"},
        triggered_at=datetime(2026, 8, 20, 6, 35, 2, tzinfo=timezone.utc),
    )
    assert "> **股票**：000001.SZ" in msg  # 无名称只显代码
    assert "查看个股" not in msg  # 无 link_base 省略链接行
