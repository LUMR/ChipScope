# 自选股配置页 + UI 重设计 设计文档

- **日期**：2026-06-15
- **状态**：已确认，待实施
- **范围**：前端（React/AntD/ECharts）+ 后端（FastAPI/PostgreSQL）

## 1. 背景与动机

ChipScope 当前自选股（watchlist）完全静态：前端 `Watchlist.tsx` 硬编码 5 只股票，后端 scheduler 从环境变量 `CHIPSCOPE_WATCHLIST` 读取监控列表。用户无法在网页上管理自选股，前端也未接入后端已有的 WebSocket 实时行情。

本次目标：

1. 新增「自选管理」配置页，支持搜索添加、拖拽排序、删除，且**联动后端监控**（增删即时影响 scheduler 采集与推送）。
2. 重新设计 UI：建立正式导航/多页面结构，采用「现代金融 SaaS」视觉风格（B 方案），保留 Ant Design 深度定制技术栈。

## 2. 目标与非目标

**目标**

- 自选股由数据库统一管理，替代环境变量作为运行时唯一来源（环境变量降级为首次 seed）
- 自选管理页：搜索添加 / 拖拽排序 / 删除 / 展示行业·现价·涨跌
- 行情页左侧常驻自选栏，支持点击切换、快速增删、实时报价
- 前端接入 WebSocket，自选股实时报价分发到侧栏/表格
- 全站视觉统一为 B 风格（明亮为主，保留暗色适配）

**非目标（YAGNI）**

- 多用户/账号系统（预留 `scope` 字段但不实现）
- 股票分组/标签（预留扩展，不做）
- 自选股导入/导出
- 行情页信息架构大改（沿用现有 K线/火焰/指标/回放区块，仅重做样式）

## 3. 信息架构与路由

| 路由 | 页面 | 说明 |
|---|---|---|
| `/` | 重定向 | → 第一只自选股的行情页 |
| `/stock/:secucode` | 行情详情 | K线 + 火焰图 + 指标 + 日期回放 |
| `/watchlist` | 自选管理 | 搜索添加 + 拖拽排序表格 + 删除 |

全局 `AppLayout`：顶部导航 + 左侧常驻自选栏 + 内容区（所有页面共享）。

## 4. 视觉系统

通过 AntD `ConfigProvider` + design token + CSS 变量统一：

- 主色 `#5b6cff`（靛蓝），圆角 `8px`，卡片柔和阴影
- 背景 `#f6f7f9`，卡片 `#fff`
- 涨跌色 token：涨 `#f5222d`、跌 `#16a34a`（A 股惯例，红涨绿跌）
- 明亮为主，保留暗色 token 适配（当前已支持双主题，不砍）
- 数字等宽/半粗体；ECharts 配色对齐主色系，火焰图蓝紫渐变

## 5. 后端设计

### 5.1 数据模型（新建 `watchlist` 表）

```
watchlist
- id          BIGINT PK
- secucode    VARCHAR(16)  FK→stock_meta.secucode
- scope       VARCHAR(32)  NOT NULL DEFAULT 'default'
- sort_order  INT          NOT NULL DEFAULT 0
- created_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
- UNIQUE (scope, secucode)
- INDEX (scope, sort_order)
```

**决策：独立表而非给 `stock_meta` 加 `is_watched` 字段。** 关注关系是用户态、有序、可扩展多分组，不应混入采集来的股票元数据。独立表语义清晰，符合现有 upsert 模式。

### 5.2 新增 API（`app/api/watchlist.py`）

| 方法 | 路径 | 行为 |
|---|---|---|
| GET | `/api/watchlist` | 列表：join `stock_meta`（名称/行业）+ 实时报价（现价/涨跌），按 `sort_order` 排序 |
| POST | `/api/watchlist` | body `{secucode}`；校验存在于 stock_meta；`sort_order` 追加末尾；重复 `ON CONFLICT DO NOTHING` |
| DELETE | `/api/watchlist/{secucode}` | 删除该行 |
| PUT | `/api/watchlist/reorder` | body `{secucodes:[...]}`；按数组顺序重写 `sort_order` |

搜索复用现有 `GET /api/stocks?q=`（按代码/名称模糊匹配 stock_meta）。

实时报价来源：复用现有 Redis 缓存（`realtime.py`，scheduler 每 3s 写入）。

### 5.3 scheduler 改造

- 启动时若 `watchlist` 表为空，用 `CHIPSCOPE_WATCHLIST` 环境变量 seed 初始数据（按顺序赋 `sort_order`），一次性
- realtime 循环每轮从 DB 读最新 secucode 列表（替代直接读环境变量）→ 网页增删即时生效
- 环境变量降级为 seed/兜底，不再作为运行时唯一来源

## 6. 前端设计

### 6.1 布局

`AppLayout`（AntD Layout）：Header=`TopNav`，Sider=`SiderWatchlist`，Content=react-router `Outlet`。

### 6.2 组件

- **TopNav**：Logo + 菜单（行情/自选管理）+ 搜索（复用现有 AutoComplete）
- **SiderWatchlist**（常驻）：每行 代码+名称+实时价+涨跌（红绿），点击跳 `/stock/:secucode`、高亮当前；底部 `+ 添加`（inline 搜索候选）；每行 hover 显示删除小图标
- **WatchlistPage**：搜索添加（候选下拉）+ 可拖拽表格（dnd-kit）+ 删除（AntD Popconfirm）；列：拖拽手柄/代码/名称/行业/现价/涨跌/操作
- **行情详情页组件**（沿用、按 B 风格重做样式）：`KLineChart`、`ChipFlame`、`MetricPanel`、`DateSlider`

### 6.3 hooks

- **useWatchlist**：封装 GET/POST/DELETE/reorder，乐观更新
- **useRealtimeQuotes**：全局单一 WebSocket 连接（App 层建立），订阅当前自选股报价，通过 Context 分发给侧栏/表格/详情页；断连指数退避重连

### 6.4 api client

`api/client.ts` 新增 `apiPost/apiDelete/apiPut`，沿用 `apiGet` 的错误处理与 `/api` 前缀。

## 7. 数据流

- **增删自选**：`前端操作 → POST/DELETE /api/watchlist → DB → scheduler 下一轮(≤3s) 读新列表 → 采集 + WS 推送 → useRealtimeQuotes 更新现价`
- **拖拽排序**：`拖放 → PUT /api/watchlist/reorder → sort_order 更新 → 侧栏/表格顺序同步`
- **实时报价**：`scheduler 每3s 采集 → Redis 缓存 → WebSocket → useRealtimeQuotes → 侧栏/表格/详情`

## 8. 错误处理

| 场景 | 处理 |
|---|---|
| 添加重复 | 后端 `ON CONFLICT DO NOTHING`，前端提示「已在自选中」 |
| 搜索无结果 | 候选空状态 |
| WebSocket 断连 | 指数退避自动重连；期间显示最近缓存值 |
| 删除 | Popconfirm 二次确认 |
| secucode 不在 stock_meta | POST 返回 400 |

## 9. 测试策略

**后端（pytest + 真实 PostgreSQL）**

- watchlist CRUD：增/删/查、重复忽略、reorder 排序正确
- scheduler 从 DB 读列表：mock 表数据，断言采集目标 = DB 列表
- seed 逻辑：空表时用环境变量初始化

**前端（vitest）**

- `useWatchlist`：增删改 + 乐观更新
- `useRealtimeQuotes`：连接/重连/分发
- `SiderWatchlist`：渲染 + 点击跳转 + hover 删除
- `WatchlistPage`：搜索候选 + 拖拽排序 + 删除确认

## 10. 关键决策记录

| 决策 | 选择 | 理由 |
|---|---|---|
| 技术栈 | 保留 AntD 深度定制 | 现有组件全基于 AntD，换 Tailwind 重写成本高、回归风险大；AntD token 定制力足够 |
| 自选股定位 | 联动后端监控 | 「管理自选股」应真正驱动系统行为，否则配置意义打折 |
| watchlist 存储 | 独立表 | 用户态/有序/可扩展，不污染股票元数据 |
| 实时行情 | 接入现有 WebSocket | 后端基础设施现成，实时性好，体现联动价值 |
| 暗色模式 | 保留双主题 | 当前已支持，砍掉是负收益 |
| 视觉风格 | B 现代 SaaS | 友好精致、易上手，适合分析工具 |
