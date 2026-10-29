# 实时盯盘告警（Alert）功能实现计划

> 状态：**已实施**（2026-08-20）。迁移 0009 已应用，测试四件套 + 全量回归通过。
> 日期：2026-08-20

## 背景与目标

为 ChipScope 增加实时盯盘能力：用户为股票配置告警规则（实时行情阈值、筹码指标、筹码形态），条件满足时发送企业微信群机器人 webhook 通知。

**已确认的需求决策：**

1. 规则存数据库 + API CRUD + 前端 UI，改规则无需重启（每 tick 从 DB 读）
2. 通知渠道：仅企业微信机器人（markdown），`Notifier` Protocol 留多渠道扩展点
3. 条件类型：实时行情（秒级）+ 筹码指标（日级）+ 形态识别（日级）
4. 监控范围：每条规则自带股票列表（独立于 watchlist 自选股）

**已核实的架构事实：**

- `backend/app/scheduler.py` 的 `realtime_loop`（interval 3s）逐只拉 `RealtimeQuote`（含 vol/amount，Redis payload 里没有这两个字段，评估必须用 quote 对象）；24/7 运行、无交易时段判断 → 告警须自带时段闸门
- `chip_distribution` 表已物化 `profit_ratio / avg_cost / concentration / cost_high / cost_low` 列；pattern 不落表，`chip_pattern.recognize()` / `recognize_trend()` 纯函数现算
- 无任何现有 webhook/notify 代码；httpx / respx / tenacity 已在依赖中，**无需新增依赖**
- 模型为 SQLAlchemy 2.0 Mapped 风格 + JSONB 先例（`models/chip.py`）；alembic 最新 0008；`tests/conftest.py` 需为新表加 model import + `_TRUNCATE_TABLES`
- 16:05 `daily_kline_chip` 目前只对 watchlist 计算筹码 → 需扩展为 watchlist ∪ 告警股票

## 实现步骤（按序）

### 1. 数据模型 + 迁移 + conftest

**新建 `backend/app/models/alert.py`**：

```python
class AlertRule(Base):
    __tablename__ = "alert_rule"
    id: int PK autoincrement
    name: str(64)
    enabled: bool = True
    secucodes: JSONB list      # ["600519.SH", ...]，API 层校验
    conditions: JSONB list     # 条件数组，AND 语义
    cooldown_minutes: int = 10
    webhook_url: str(512) | None    # 空 → 全局配置默认值
    created_at / updated_at: TIMESTAMPTZ server_default=func.now()

class AlertEvent(Base):
    __tablename__ = "alert_event"
    __table_args__ = (Index("ix_alert_event_rule_secucode_ts", "rule_id", "secucode", "triggered_at"),)
    id: int PK
    rule_id: FK alert_rule.id ondelete=CASCADE
    rule_name / stock_name: str          # 快照，防规则改名/删股票后历史不可读
    secucode: str(12)
    triggered_at: TIMESTAMPTZ server_default=now()
    trade_date: Date | None              # 日级去重键
    status: str(16) = "pending"          # pending / sent / failed / skipped
    payload: JSONB                       # 触发时刻指标快照
    message: Text                        # 渲染好的 markdown 快照
    detail: Text | None                  # 失败原因
```

设计决策：

- 股票列表用 JSONB 数组（同 `chip.distribution` 惯例），完整性靠 API 层校验（复用 `app/api/watchlist.py` 的 `_ensure_stock_meta` 自动补录 stock_meta）
- **不在 rule 上放 last_triggered_at** — cooldown 语义是 per (rule, stock)，放 rule 上语义错误；统一查 `alert_event`（有索引），单一事实源，避免双写竞态

**新建 `backend/alembic/versions/0009_alerts.py`**（revision="0009"，down_revision="0008"，仿 0008 手写 create_table + index；downgrade drop）。

**修改 `backend/tests/conftest.py`**：`import app.models.alert  # noqa: F401`，`_TRUNCATE_TABLES` 追加 `alert_rule, alert_event`。

### 2. 配置

**修改 `backend/app/config.py`**：

| 字段 | 默认 | env | 说明 |
|---|---|---|---|
| `alert_webhook_url` | `""` | `CHIPSCOPE_ALERT_WEBHOOK_URL` | 全局默认企业微信机器人 webhook |
| `alert_link_base` | `""` | `CHIPSCOPE_ALERT_LINK_BASE` | 消息里「查看个股」链接前缀，空则省略链接行 |

### 3. 条件 DSL + 评估引擎（核心）

**新建 `backend/app/services/alert_engine.py`**。

#### 条件 DSL（JSONB 数组，AND 语义）

```json
{"scope": "realtime", "metric": "pct_change",   "op": "gte", "value": 5.0}
{"scope": "chip",     "metric": "profit_ratio", "op": "cross_above", "value": 0.8}
{"scope": "pattern",  "metric": "pattern",      "op": "eq", "value": "single_peak_dense"}
```

metric 注册表（模块常量，同时供 API 校验与 `GET /api/alerts/metrics` 前端下拉）：

| scope | metric | 说明 |
|---|---|---|
| realtime | `price` / `open` / `high` / `low`（元） | RealtimeQuote 字段 |
| realtime | `pct_change`（%，现算 `(price-last_close)/last_close*100`） | RealtimeQuote |
| realtime | `vol`（手）/ `amount`（元） | RealtimeQuote（Redis 无，必须用 quote 对象） |
| chip | `profit_ratio`、`concentration`（0-1） | chip_distribution 列 |
| chip | `avg_cost` / `cost_high` / `cost_low`（元） | chip_distribution 列 |
| pattern | `pattern`：`single_peak_dense` / `high_single_peak` / `low_single_peak` / `divergent` / `none` | `recognize()` 现算，中文形态名→英文 key 映射 |
| pattern | `trend`：`cost_up` / `cost_down` / `none` | `recognize_trend(近30日 avg_cost 序列)` 现算 |

操作符：

- `gt / lt / gte / lte` — 电平触发，配 cooldown 去重
- `cross_above / cross_below` — 边沿触发（`cur > value and prev <= value` / 反之）
- `eq / ne` — 仅 pattern 字符串条件

关键规则：

- **cross 前值来源**：realtime 用引擎内 `EdgeState`（`dict[secucode] → 上一 tick 的指标值`，评估在先、更新在后，无前值判 False）；chip 用 DB 倒数第二行 snapshot，评估上下文以 `"prev:profit_ratio"` 形式提供
- **scope 分组约束**：一条规则的 conditions 必须全为 `realtime`，或全在 `{chip, pattern}`（日级二者可混）；混用返回 422（Pydantic `model_validator`）。保证语义清晰：实时规则在 realtime_loop 评估、日级规则在 16:20 job 评估

#### 函数结构

```python
# 纯函数（无 I/O，直接单测）
in_trading_window(now) -> bool           # 周一~五 09:15-11:35 / 12:55-15:05 CST（带缓冲）
build_realtime_values(quote) -> dict     # 含 pct_change 现算
build_daily_values(chips, current_price) -> dict   # chip 列 + pattern/trend 现算 + prev:*
evaluate_conditions(conditions, values) -> bool
describe_rule(conditions) -> str         # "涨跌幅(%) ≥ 5 且 成交额(元) > 1000000000"

# 编排（session_factory 可注入，照抄 read_watchlist_secucodes 模式）
load_active_rules(session_factory) -> (rules, secucode→name 映射)
evaluate_realtime(session_factory, rules, names, secucode, quote, edge_state)
evaluate_daily(session_factory)           # 读最新/次新 chip snapshot，trade_date 去重
_cooldown_blocked(...)                    # realtime：triggered_at > now - cooldown
_fired_today(...)                         # daily：event.trade_date == trade_date
```

#### 触发流程 `_fire`

1. INSERT `alert_event(status="pending")` + commit — **先落库占位**，天然防止发送期间重复触发
2. `asyncio.create_task(_send_and_update(...))` 放模块级 `_background_tasks` set（照抄 `api/watchlist.py` 模式），task 内自建 `SessionLocal` session，不阻塞 realtime_loop
3. 发送成功 → `sent`；失败 → `failed` + detail；无 webhook 配置 → `skipped`

性能：每 tick 仅 1 次规则 SELECT；条件不通过零额外 DB 查询；条件通过才查 cooldown。DB 中的坏条件（未知 metric/op）skip + log，不抛异常，防止单条脏数据打断 realtime_loop。

### 4. 通知服务

**新建 `backend/app/services/notify.py`**：

- `Notifier` Protocol（`async send_markdown(content)`）+ `WecomWebhook` 首个实现（多渠道扩展点）
- POST `https://qyapi.weixin.qq.com/cgi-bin/webhook/send`，body `{"msgtype":"markdown","markdown":{"content":...}}`，timeout=10
- tenacity 重试仅针对 TransportError/Timeout（3 次指数退避 1s→2s→4s，仿 `services/retry.py`）；`errcode != 0` 直接抛 NotifyError 不重试（业务错误重试无意义）
- **频率保护**：模块级 `asyncio.Lock` + 上次发送时间戳，串行化发送且间隔 ≥3s（≤20 条/分钟，匹配企业微信限制）
- `render_alert_markdown(rule_name, stock_name, secucode, cond_desc, values, triggered_at, link_base)` 纯函数，模板：

```markdown
## <font color="warning">🔔 ChipScope 盯盘告警</font>
> **规则**：涨幅超5%
> **股票**：贵州茅台（600519.SH）
> **时间**：2026-08-20 14:35:02
> **条件**：涨跌幅(%) ≥ 5
> **现值**：<font color="warning">涨跌幅 +5.23% / 现价 1689.00</font>
> [查看个股](http://localhost:8001/stock/600519.SH)
```

（triggered_at 渲染为 CST；link_base 为空时省略链接行）

### 5. 调度挂点

**修改 `backend/app/scheduler.py`**（三处）：

1. `realtime_loop`：每 tick `load_active_rules(SessionLocal)` 一次 → 拉取列表改 `secucodes = list(dict.fromkeys(watchlist + alert_codes))`（去重保序）→ 每只股票拉到 quote、cache、broadcast 之后：`if rules and in_trading_window(now): await evaluate_realtime(...)`；模块级 `edge_state` 单例
2. `daily_kline_chip`（16:05）：计算范围改 **watchlist ∪ 活跃 alert 规则股票**（差集补 `StockMeta.secucode.in_(diff)` 查询；缺 secid / stock_meta 缺失则打日志跳过，不中断）
3. `build_scheduler()` 新增 job `daily_alerts`（CronTrigger 16:20，包装 `evaluate_daily`）。选独立 cron 而非链在 16:05 末尾：失败隔离、可测、且 `alert_event.trade_date` 去重使重复评估安全；若 16:05 任务超时跨过 16:20，部分股票会评到旧快照，属可接受降级

### 6. API

**新建 `backend/app/schemas/alert.py`**：

- `AlertCondition`：scope / metric / op / value（metric ∈ 注册表；pattern 条件强制 eq/ne，数值条件禁止 eq/ne；pattern 值为 str，其余为 float）
- `AlertRuleCreate`：name（1-64）、secucodes（≥1）、conditions（≥1）、enabled、cooldown_minutes（1-1440，默认 10）、webhook_url（可空）；`model_validator` 校验 scope 同组
- `AlertRuleOut`（+id/created_at/updated_at，from_attributes）、`AlertEventOut`、`TestResult`

**新建 `backend/app/api/alerts.py`**（`prefix="/api/alerts", tags=["alerts"]`）：

| 端点 | 说明 |
|---|---|
| `GET /metrics` | metric 注册表（前端条件下拉动态渲染，避免前后端各维护一份） |
| `GET /rules` → `POST /rules`（201） | 列表 / 新建；secucode 不在 stock_meta 时复用 `_ensure_stock_meta` 自动补录，仍查无则 400 |
| `PUT /rules/{id}`（200 全量替换）→ `DELETE /rules/{id}`（204） | 修改 / 删除 |
| `GET /events?limit=100&rule_id=` | 触发历史，triggered_at desc |
| `POST /rules/{id}/test` | 渲染样例消息直接发送（不写 event）；400 未配 webhook / 502 发送失败 |

**修改 `backend/app/main.py`**：import + `app.include_router(alerts_router)`。

### 7. 前端

- **新建 `frontend/src/api/alerts.ts`**：类型（AlertRule / AlertCondition / AlertEvent / MetricInfo）+ `listMetrics / listRules / createRule / updateRule / deleteRule / listEvents / testRule`（走 `client.ts` 包装）
- **新建 `frontend/src/pages/AlertsPage.tsx`**（布局参考 ScreenerPage，antd Tabs）：
  - 「规则」tab：Table（名称 / 股票数+Tooltip 列表 / 条件描述 / cooldown / enabled Switch 乐观更新走 PUT / 操作：编辑・测试・删除）+「新建规则」按钮
  - 编辑 Modal：名称 Input；股票 `Select mode="multiple" showSearch`（搜索走现有 `GET /api/stocks?q=`）；条件构造器 = `Form.List` 动态行（scope Select → metric Select（按 /metrics 过滤）→ op Select → value，pattern 值用 Select、其余 InputNumber），行可增删；cooldown InputNumber；webhook Input（placeholder「留空用全局配置」）
  - 「触发历史」tab：Table（时间 desc / 规则 / 股票 / 状态 Tag：sent 绿・failed 红・pending 蓝・skipped 灰 / message 点击 Drawer 展开快照）
- **修改 `frontend/src/App.tsx`**：加 `/alerts` 路由
- **修改 `frontend/src/components/TopNav.tsx`**：菜单加「盯盘告警」项 + activeKey 前缀匹配

### 8. 测试（每步完成即跑对应文件，最后全量回归）

| 文件 | 内容 |
|---|---|
| `tests/test_alert_engine.py`（纯函数，无需 DB） | values 构建、各 op 电平判断、cross 有/无前值、pattern 判定与中英映射、`in_trading_window` 边界（09:14 F / 09:16 T / 周六 F）、describe_rule、scope 混用 |
| `tests/test_notify.py`（respx mock 企业微信 URL） | errcode=0 成功；errcode≠0 → NotifyError 且不重试（called once）；TransportError→重试成功；render 模板断言（含 font 标签、链接可选） |
| `tests/test_api_alerts.py`（仿 test_api_screener） | CRUD 全流程、混 scope 422、未知 metric 422、未知股票 400、events 列表、test 端点 |
| `tests/test_alert_flow.py`（真 PG） | evaluate_daily 触发→pending、同 trade_date 二次评估不重复触发、evaluate_realtime cooldown 去重、realtime_loop 并集逻辑 |

## 风险与注意事项

1. **非交易时段**：realtime_loop 24/7 运行且无时段闸门，电平条件收盘后会按 cooldown 周期整夜重复触发 → 评估入口强制 `in_trading_window`；节假日不识别（已知限制，日级靠 trade_date 去重兜底）
2. **并集去重**：watchlist 与 alert 股票重叠时用 `dict.fromkeys` 去重保序；alert-only 股票进 loop 后也会被 cache/broadcast，属无害副作用
3. **webhook 频率**：企业微信 20 条/分钟 → Lock + 3s 间隔串行化；多股票同规则各自独立事件属预期
4. **session 生命周期**：后台发送 task 自建 `SessionLocal`（请求级 session 已关）；realtime 路径只在条件通过时才开 session
5. **Redis payload 无 vol/amount**：评估一律用 quote 对象，禁止从 Redis 取值
6. **测试隔离**：`EdgeState` 模块级单例会跨用例残留 — 测试注入新实例或提供 reset
7. **双进程模式**（`CHIPSCOPE_SCHEDULER_ENABLED=false` + 独立 scheduler）：告警只在跑 scheduler 的进程内生效，与现有 realtime 行为一致，无需额外处理

## 验证方式

1. 后端：`cd backend && alembic upgrade head` → `pytest tests/test_alert_engine.py tests/test_notify.py tests/test_api_alerts.py tests/test_alert_flow.py -v` → 全量 `pytest`（需 docker PG:5433 + Redis）
2. 前端：`cd frontend && npm run build && npm run lint`
3. 手动端到端：`.env` 配 `CHIPSCOPE_ALERT_WEBHOOK_URL` → 启 `uvicorn app.main:app --port 8001` → 前端建规则（如 600519.SH，pct_change gte 1，cooldown 5）→ 点「测试」验证群机器人收消息 → 交易时段观察群消息与触发历史 status 变化（pending→sent）→ 盘后验证不再触发 → 改 enabled/cooldown 即时生效（无需重启，规则每 tick 从 DB 读）
