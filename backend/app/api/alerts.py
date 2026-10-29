from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.api.watchlist import _ensure_stock_meta
from app.config import get_settings
from app.models.alert import AlertEvent, AlertRule
from app.models.stock import StockMeta
from app.schemas.alert import (
    AlertEventOut,
    AlertRuleCreate,
    AlertRuleOut,
    MetricInfoOut,
    TestResult,
)
from app.services.alert_engine import (
    METRICS,
    describe_rule,
    display_values,
    sample_values,
)
from app.services.notify import WecomWebhook, render_alert_markdown

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


@router.get("/metrics", response_model=list[MetricInfoOut])
async def list_metrics():
    """metric 注册表：前端条件下拉动态渲染，避免前后端各维护一份。"""
    return [
        MetricInfoOut(
            scope=m.scope,
            metric=m.metric,
            label=m.label,
            ops=list(m.ops),
            options=[{"value": v, "label": l} for v, l in m.options],
        )
        for m in METRICS
    ]


async def _ensure_secucodes(db: AsyncSession, secucodes: list[str]) -> None:
    """stock_meta 缺失的 secucode 自动补录（东财查证），仍查无则 400。"""
    existing = set(
        (
            await db.execute(
                select(StockMeta.secucode).where(StockMeta.secucode.in_(secucodes))
            )
        ).scalars().all()
    )
    for code in secucodes:
        if code in existing:
            continue
        meta = await _ensure_stock_meta(db, code)
        if meta is None or meta.secucode != code:
            raise HTTPException(status_code=400, detail=f"stock not found: {code}")


async def _get_rule(db: AsyncSession, rule_id: int) -> AlertRule:
    rule = (
        await db.execute(select(AlertRule).where(AlertRule.id == rule_id))
    ).scalar_one_or_none()
    if rule is None:
        raise HTTPException(status_code=404, detail="rule not found")
    return rule


@router.get("/rules", response_model=list[AlertRuleOut])
async def list_rules(db: AsyncSession = Depends(get_db)):
    return (
        (await db.execute(select(AlertRule).order_by(AlertRule.id))).scalars().all()
    )


@router.post("/rules", response_model=AlertRuleOut, status_code=201)
async def create_rule(body: AlertRuleCreate, db: AsyncSession = Depends(get_db)):
    await _ensure_secucodes(db, body.secucodes)
    rule = AlertRule(**body.model_dump())
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return rule


@router.put("/rules/{rule_id}", response_model=AlertRuleOut)
async def update_rule(
    rule_id: int, body: AlertRuleCreate, db: AsyncSession = Depends(get_db)
):
    """全量替换（含 enabled 开关的乐观更新）。"""
    rule = await _get_rule(db, rule_id)
    await _ensure_secucodes(db, body.secucodes)
    for k, v in body.model_dump().items():
        setattr(rule, k, v)
    await db.commit()
    await db.refresh(rule)
    return rule


@router.delete("/rules/{rule_id}", status_code=204)
async def delete_rule(rule_id: int, db: AsyncSession = Depends(get_db)):
    rule = await _get_rule(db, rule_id)
    await db.delete(rule)  # alert_event 由 FK CASCADE 级联删除
    await db.commit()
    return Response(status_code=204)


@router.get("/events", response_model=list[AlertEventOut])
async def list_events(
    limit: int = Query(100, ge=1, le=500),
    rule_id: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(AlertEvent).order_by(AlertEvent.triggered_at.desc()).limit(limit)
    if rule_id is not None:
        stmt = stmt.where(AlertEvent.rule_id == rule_id)
    return (await db.execute(stmt)).scalars().all()


@router.post("/rules/{rule_id}/test", response_model=TestResult)
async def test_rule(rule_id: int, db: AsyncSession = Depends(get_db)):
    """渲染样例消息直接发送（不写 alert_event）。

    400 未配 webhook；502 发送失败。样例现值取引擎演示值。
    """
    rule = await _get_rule(db, rule_id)
    webhook = rule.webhook_url or get_settings().alert_webhook_url
    if not webhook:
        raise HTTPException(
            status_code=400,
            detail="未配置 webhook（规则 webhook_url 或 CHIPSCOPE_ALERT_WEBHOOK_URL）",
        )
    secucode = rule.secucodes[0]
    stock_name = (
        await db.execute(select(StockMeta.name).where(StockMeta.secucode == secucode))
    ).scalar_one_or_none() or ""
    message = render_alert_markdown(
        rule_name=rule.name,
        stock_name=stock_name,
        secucode=secucode,
        cond_desc=describe_rule(rule.conditions),
        values=display_values(rule.conditions, sample_values()),
        triggered_at=datetime.now(timezone.utc),
        link_base=get_settings().alert_link_base,
    )
    try:
        await WecomWebhook(webhook).send_markdown(message)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"发送失败: {e}")
    return TestResult(ok=True, message=message)
