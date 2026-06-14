# ChipScope 筹码分布计算引擎 Implementation Plan (Plan 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans.

**Goal:** 实现筹码分布计算引擎——按三角形分布法把每日成交量分配到价格区间，用衰减系数叠加历史筹码，计算衍生指标（获利盘/集中度/平均成本/筹码峰）并做形态识别，落库 chip_distribution，提供 REST 查询。

**Architecture:** 纯 NumPy 向量化计算，无外部网络依赖（不受东财限流影响）。核心是 `ChipEngine`：输入日K序列（按日K表）+ 衰减系数（holder_summary），逐日迭代产出到每日分布快照。衍生指标和形态识别是分布的纯函数，易 TDD。

**Tech Stack:** NumPy（已装）、Plan 1/2 已有的 SQLAlchemy/asyncpg/FastAPI。

**关键设计决策（落实审查 P0-4）：**
1. **价格分箱**：固定 400 个 bin 覆盖 [序列最低价×0.9, 序列最高价×1.1]，步长 = 区间/399。落库时存 `{price_label: ratio}`（ratio 归一化到 0-1，省空间）。
2. **三角形分布**：当日成交量按以 VWAP 为峰、[low, high] 为底的三角形分配到 bin。归一化使三角形积分 = 当日成交量。
3. **衰减叠加**（修 P0-4 负权重）：`effective_turnover = min(turnover_rate * decay_coeff / 100, 0.95)`，`dist = today_tri * eff + old_dist * (1 - eff)`。截断 0.95 保证旧筹码权重 ≥ 0.05。
4. 衰减系数从 holder_summary 取最近一期；回填历史用最新季度（设计文档已知局限）。
5. 分布内部用 NumPy 数组，落库 JSONB 时转 dict。

---

## File Structure

```
backend/app/
├── services/
│   ├── chip_engine.py     # 价格分箱 + 三角形分布 + 衰减叠加（核心）
│   ├── chip_metrics.py    # 衍生指标（获利盘/集中度/均成本/峰）
│   ├── chip_pattern.py    # 形态识别
│   └── chip_compute.py    # 编排：日K序列 → 分布快照落库
├── models/chip.py         # ChipDistribution
├── schemas/chip.py
├── api/chips.py           # /chips /chips/history /pattern
└── (alembic/versions/0003_chip_distribution.py)
backend/tests/
├── test_chip_engine.py    # 核心算法 TDD
├── test_chip_metrics.py
├── test_chip_pattern.py
└── test_api_chips.py
```

---

## Task 1: chip_distribution 表 + 模型 + 迁移 0003

**Files:** `models/chip.py`, `alembic/versions/0003_chip_distribution.py`, `alembic/env.py`

- [ ] **Step 1: models/chip.py**

```python
from datetime import datetime
from sqlalchemy import DateTime, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base


class ChipDistribution(Base):
    __tablename__ = "chip_distribution"
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    secucode: Mapped[str] = mapped_column(String(12), primary_key=True)
    distribution: Mapped[dict] = mapped_column(JSONB)  # {"15.00": 0.08, ...} ratio
    decay_coeff: Mapped[float] = mapped_column(Numeric(6, 2))
    concentration: Mapped[float] = mapped_column(Numeric(8, 4))   # 90%集中度
    cost_high: Mapped[float] = mapped_column(Numeric(10, 3))
    cost_low: Mapped[float] = mapped_column(Numeric(10, 3))
    profit_ratio: Mapped[float] = mapped_column(Numeric(8, 4))
    avg_cost: Mapped[float] = mapped_column(Numeric(10, 3))
```

- [ ] **Step 2: 迁移 0003**（建表 + hypertable + GIN 索引）

```python
"""chip_distribution table

Revision ID: 0003
Revises: 0002
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chip_distribution",
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("secucode", sa.String(12), nullable=False),
        sa.Column("distribution", postgresql.JSONB),
        sa.Column("decay_coeff", sa.Numeric(6, 2)),
        sa.Column("concentration", sa.Numeric(8, 4)),
        sa.Column("cost_high", sa.Numeric(10, 3)),
        sa.Column("cost_low", sa.Numeric(10, 3)),
        sa.Column("profit_ratio", sa.Numeric(8, 4)),
        sa.Column("avg_cost", sa.Numeric(10, 3)),
        sa.PrimaryKeyConstraint("secucode", "ts"),
    )
    op.execute("SELECT create_hypertable('chip_distribution', 'ts', "
               "chunk_time_interval => INTERVAL '30 days', if_not_exists => TRUE);")
    op.execute("CREATE INDEX idx_chip_dist_gin ON chip_distribution USING GIN (distribution);")


def downgrade() -> None:
    op.drop_table("chip_distribution")
```

- [ ] **Step 3: env.py 注册 + 跑迁移 + Commit**

```python
import app.models.chip  # noqa: F401
```
```bash
.venv/Scripts/alembic upgrade head
git add -A && git commit -m "feat(db): chip_distribution hypertable + GIN index"
```

---

## Task 2: 价格分箱 + 三角形分布（核心，TDD）

**Files:** `services/chip_engine.py`, `tests/test_chip_engine.py`

- [ ] **Step 1: 写失败测试（先）**

```python
import numpy as np
import pytest
from app.services.chip_engine import price_bins, triangle_distribution, decay_step


def test_price_bins_covers_range():
    centers, step = price_bins(low=10.0, high=20.0, num=400)
    assert len(centers) == 400
    assert centers[0] == pytest.approx(10.0)
    assert centers[-1] == pytest.approx(20.0)


def test_triangle_distribution_peak_at_vwap():
    centers, _ = price_bins(low=10.0, high=20.0, num=400)
    tri = triangle_distribution(centers, low=10.0, vwap=15.0, high=20.0, volume=10000.0)
    # 总量 = volume
    assert tri.sum() == pytest.approx(10000.0, rel=1e-4)
    # 峰在 vwap 附近（最大值索引接近 vwap）
    assert centers[np.argmax(tri)] == pytest.approx(15.0, abs=0.1)
    # 两端为 0
    assert tri[0] == pytest.approx(0.0, abs=1e-6)
    assert tri[-1] == pytest.approx(0.0, abs=1e-6)


def test_decay_step_caps_effective_turnover():
    """P0-4: 有效换手率截断 0.95，防止旧筹码权重为负。"""
    old = np.ones(400) * 100.0
    today = np.ones(400) * 50.0
    # 换手率 30%，衰减系数 5 → 有效换手率 1.5 → 截断 0.95
    new = decay_step(old, today, turnover_rate=30.0, decay_coeff=5.0)
    # 旧权重 = 1 - 0.95 = 0.05，旧筹码贡献 100*0.05=5
    # 新权重 0.95，新筹码 50*0.95=47.5
    assert new[0] == pytest.approx(5.0 + 47.5, rel=1e-4)


def test_decay_step_normal_case():
    old = np.ones(400) * 100.0
    today = np.ones(400) * 0.0
    # 换手率 5%，衰减 2 → 有效换手率 0.1
    new = decay_step(old, today, turnover_rate=5.0, decay_coeff=2.0)
    assert new[0] == pytest.approx(100.0 * 0.9, rel=1e-4)
```

- [ ] **Step 2: 运行测试看失败**

```bash
.venv/Scripts/python -m pytest tests/test_chip_engine.py -v
```
Expected: ImportError（chip_engine 未定义）。

- [ ] **Step 3: 实现 chip_engine.py**

```python
import numpy as np


def price_bins(low: float, high: float, num: int = 400):
    """返回 bin 中心数组 + 步长。覆盖 [low, high]，num 个等距 bin。"""
    centers = np.linspace(low, high, num)
    step = (high - low) / (num - 1) if num > 1 else 0.0
    return centers, step


def triangle_distribution(centers, low: float, vwap: float, high: float, volume: float):
    """以 vwap 为峰、[low,high] 为底的三角形分布，归一化总量 = volume。"""
    centers = np.asarray(centers, dtype=float)
    tri = np.zeros_like(centers)
    left = centers <= vwap
    right = ~left
    # 左半：从 low 上升到 vwap
    denom_l = (vwap - low) or 1e-9
    tri[left] = (centers[left] - low) / denom_l
    # 右半：从 vwap 下降到 high
    denom_r = (high - vwap) or 1e-9
    tri[right] = (high - centers[right]) / denom_r
    tri = np.clip(tri, 0.0, None)
    total = tri.sum()
    if total > 0:
        tri = tri / total * volume
    return tri


def decay_step(old_dist, today_tri, turnover_rate: float, decay_coeff: float):
    """衰减叠加（P0-4 截断）。

    effective_turnover = min(turnover_rate * decay_coeff / 100, 0.95)
    new = today_tri * eff + old_dist * (1 - eff)
    """
    eff = min(turnover_rate * decay_coeff / 100.0, 0.95)
    return today_tri * eff + np.asarray(old_dist) * (1.0 - eff)
```

- [ ] **Step 4: 测试通过 + Commit**

```bash
.venv/Scripts/python -m pytest tests/test_chip_engine.py -v
git add -A && git commit -m "feat(chip): price bins + triangle distribution + decay step"
```

---

## Task 3: 衍生指标（获利盘/集中度/均成本/峰）

**Files:** `services/chip_metrics.py`, `tests/test_chip_metrics.py`

- [ ] **Step 1: 测试（先）**

```python
import numpy as np
import pytest
from app.services.chip_metrics import profit_ratio, avg_cost, concentration_90, peak_price


def test_profit_ratio():
    centers = np.array([10.0, 15.0, 20.0])
    dist = np.array([30.0, 50.0, 20.0])
    # 现价 15：price<=15 的筹码 = 30+50=80，总 100 → 0.8
    assert profit_ratio(centers, dist, current_price=15.0) == pytest.approx(0.8)


def test_avg_cost():
    centers = np.array([10.0, 20.0])
    dist = np.array([50.0, 50.0])
    assert avg_cost(centers, dist) == pytest.approx(15.0)


def test_concentration_90():
    # 全集中在 15 一个价位 → 90% 区间为 0
    centers = np.array([10.0, 15.0, 20.0])
    dist = np.array([0.0, 100.0, 0.0])
    low, high, conc = concentration_90(centers, dist)
    assert conc == pytest.approx(0.0, abs=0.05)


def test_peak_price():
    centers = np.array([10.0, 15.0, 20.0])
    dist = np.array([10.0, 80.0, 10.0])
    assert peak_price(centers, dist) == pytest.approx(15.0)
```

- [ ] **Step 2: 实现 chip_metrics.py**

```python
import numpy as np


def profit_ratio(centers, dist, current_price: float) -> float:
    centers = np.asarray(centers); dist = np.asarray(dist, dtype=float)
    total = dist.sum()
    if total == 0:
        return 0.0
    in_profit = dist[centers <= current_price].sum()
    return float(in_profit / total)


def avg_cost(centers, dist) -> float:
    centers = np.asarray(centers); dist = np.asarray(dist, dtype=float)
    total = dist.sum()
    if total == 0:
        return 0.0
    return float((centers * dist).sum() / total)


def concentration_90(centers, dist):
    """返回 (cost_low_90, cost_high_90, concentration)。

    90% 区间：从两端各去掉 5% 筹码后的边界。
    集中度 = (high-low)/(high+low)*2。
    """
    centers = np.asarray(centers); dist = np.asarray(dist, dtype=float)
    total = dist.sum()
    if total == 0:
        return 0.0, 0.0, 0.0
    cum = np.cumsum(dist)
    low_idx = np.searchsorted(cum, total * 0.05)
    high_idx = np.searchsorted(cum, total * 0.95)
    low_idx = min(low_idx, len(centers) - 1)
    high_idx = min(high_idx, len(centers) - 1)
    cl = float(centers[low_idx]); ch = float(centers[high_idx])
    conc = (ch - cl) / (ch + cl) * 2 if (ch + cl) > 0 else 0.0
    return cl, ch, float(conc)


def peak_price(centers, dist) -> float:
    centers = np.asarray(centers); dist = np.asarray(dist, dtype=float)
    if dist.sum() == 0:
        return 0.0
    return float(centers[int(np.argmax(dist))])
```

- [ ] **Step 3: 测试通过 + Commit**

---

## Task 4: 形态识别

**Files:** `services/chip_pattern.py`, `tests/test_chip_pattern.py`

按设计文档 8 的规则。输入：分布指标（concentration, peak_ratio, current_price vs peak, avg_cost 30天趋势）。

- [ ] **单峰密集**：concentration_90 < 0.15 且 peak 区(±2%)占比 > 0.40
- [ ] **筹码发散**：concentration_90 > 0.30
- [ ] **高位单峰**：单峰密集 + current_price > peak * 1.05
- [ ] **低位单峰**：单峰密集 + current_price < peak * 0.95
- [ ] **筹码下移/上移**：近 30 天 avg_cost 单调降/升

实现 `recognize(metrics, current_price, avg_cost_series) -> dict`，返回形态名+置信度。测试覆盖每个形态的边界。Commit。

---

## Task 5: 筹码计算编排（日K序列 → 分布序列落库）

**Files:** `services/chip_compute.py`, `tests/test_chip_compute.py`

- [ ] **compute_chip_series(klines, decay_coeff, num_bins=400)**：输入日K list（含 high/low/vwap/volume/turnover/close），输出每日 (ts, dist_array, centers, metrics)。

```python
def compute_chip_series(klines, decay_coeff, num_bins=400):
    lows = [k["low"] for k in klines]
    highs = [k["high"] for k in klines]
    lo, hi = min(lows) * 0.9, max(highs) * 1.1
    centers, _ = price_bins(lo, hi, num_bins)
    old_dist = np.zeros(num_bins)
    results = []
    for k in klines:
        today_tri = triangle_distribution(centers, k["low"], k["vwap"], k["high"], k["volume"])
        new_dist = decay_step(old_dist, today_tri, k["turnover_rate"], decay_coeff)
        cl, ch, conc = concentration_90(centers, new_dist)
        results.append({
            "ts": k["ts"], "dist": new_dist, "centers": centers,
            "close": k["close"],
            "profit_ratio": profit_ratio(centers, new_dist, k["close"]),
            "avg_cost": avg_cost(centers, new_dist),
            "cost_low": cl, "cost_high": ch, "concentration": conc,
            "peak": peak_price(centers, new_dist),
        })
        old_dist = new_dist
    return centers, results
```

- [ ] **upsert_chip_distribution(session, secucode, results, decay_coeff)**：把 dist 转成 `{price_label: ratio}` JSONB，落库。

测试：给定 3 天日K，验证分布随天数累积、指标合理。Commit。

---

## Task 6: REST API（/chips /chips/history /pattern）

**Files:** `schemas/chip.py`, `api/chips.py`, `main.py` 挂载, `tests/test_api_chips.py`

- `GET /api/stocks/{code}/chips?date=` → 最新或指定日分布 + 指标 + 形态
- `GET /api/stocks/{code}/chips/history` → 获利盘/集中度趋势序列
- `GET /api/stocks/{code}/pattern` → 形态识别结果

参照 Plan 1/2 的 api_client fixture 模式。Commit。

---

## Task 7: 端到端（mock 日K序列计算筹码）

`scripts/smoke_chip.py`：构造 60 天合成日K序列（含一次放量），compute_chip_series，落库，查 API 验证。纯本地计算，不依赖东财。Commit。

---

## Self-Review

**Spec coverage：** 筹码算法(4.1-4.5)、衍生指标(4.4)、形态识别(八)、chip_distribution 表(3.1)、API /chips /pattern(5.2)。P0-4 衰减截断已落实（Task 2 test_decay_step_caps）。

**纯计算无外部依赖**：整个 Plan 3 不请求东财/mootdx，完全可测试、可验证。

**未覆盖（Plan 4）：** 前端 K线/火焰图/指标面板。
