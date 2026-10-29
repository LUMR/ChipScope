from datetime import date, datetime
import re

from pydantic import BaseModel, Field, model_validator

from app.services.alert_engine import METRIC_INDEX, rule_kind

_SECUCODE_RE = re.compile(r"^\d{6}\.(SH|SZ)$")


class AlertCondition(BaseModel):
    """单条条件：{scope, metric, op, value}。metric ∈ 引擎注册表。"""

    scope: str  # realtime / chip / pattern
    metric: str
    op: str
    value: float | str  # 数值条件为 float，pattern/trend 为英文 key 字符串

    @model_validator(mode="after")
    def _check_metric(self):
        m = METRIC_INDEX.get((self.scope, self.metric))
        if m is None:
            raise ValueError(f"未知 metric: {self.scope}.{self.metric}")
        if self.op not in m.ops:
            raise ValueError(f"{self.scope}.{self.metric} 不支持操作符 {self.op}")
        if m.is_enum != isinstance(self.value, str):
            raise ValueError(
                f"{self.scope}.{self.metric} 的 value 应为"
                + ("字符串枚举值" if m.is_enum else "数值")
            )
        if m.is_enum and self.value not in dict(m.options):
            raise ValueError(f"{self.metric} 取值非法: {self.value}")
        return self


class AlertRuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    secucodes: list[str] = Field(min_length=1)
    conditions: list[AlertCondition] = Field(min_length=1)
    enabled: bool = True
    cooldown_minutes: int = Field(default=10, ge=1, le=1440)
    webhook_url: str | None = Field(default=None, max_length=512)

    @model_validator(mode="after")
    def _check_rule(self):
        # realtime 规则在 realtime_loop 评估、日级规则在 16:20 job 评估，
        # 混用无法归入单一评估路径 → 拒绝
        if rule_kind([c.model_dump() for c in self.conditions]) is None:
            raise ValueError(
                "conditions 的 scope 必须全为 realtime，或全在 {chip, pattern}（可混）"
            )
        for s in self.secucodes:
            if not _SECUCODE_RE.match(s):
                raise ValueError(f"secucode 格式非法（应为 600519.SH）: {s}")
        if len(set(self.secucodes)) != len(self.secucodes):
            raise ValueError("secucodes 不得重复")
        return self


class AlertRuleOut(BaseModel):
    """规则响应。conditions 为 DB 快照原样返回（脏数据不炸响应）。"""

    id: int
    name: str
    enabled: bool
    secucodes: list[str]
    conditions: list[dict]
    cooldown_minutes: int
    webhook_url: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AlertEventOut(BaseModel):
    id: int
    rule_id: int
    rule_name: str
    stock_name: str
    secucode: str
    triggered_at: datetime
    trade_date: date | None
    status: str  # pending / sent / failed / skipped
    payload: dict
    message: str
    detail: str | None

    model_config = {"from_attributes": True}


class MetricInfoOut(BaseModel):
    scope: str
    metric: str
    label: str
    ops: list[str]
    options: list[dict]  # [{value, label}]；数值 metric 为空


class TestResult(BaseModel):
    ok: bool
    message: str
