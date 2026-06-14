import { Card, Statistic, Tag } from "antd";
import type { ChipDistribution, PatternResult } from "../types/domain";
import { fmt, pct } from "../utils/format";

export default function MetricPanel({
  chip,
  pattern,
}: {
  chip?: ChipDistribution;
  pattern?: PatternResult;
}) {
  return (
    <Card title="筹码指标" size="small">
      <div style={{ display: "flex", gap: 24, flexWrap: "wrap", alignItems: "center" }}>
        <Statistic title="获利盘" value={chip ? pct(chip.profit_ratio) : "-"} />
        <Statistic title="90%集中度" value={chip ? pct(chip.concentration) : "-"} />
        <Statistic title="平均成本" value={chip ? fmt(chip.avg_cost) : "-"} />
        <div>
          <div style={{ color: "#888", fontSize: 12 }}>成本区间</div>
          <div>{chip ? `${fmt(chip.cost_low)} ~ ${fmt(chip.cost_high)}` : "-"}</div>
        </div>
        <div>
          <div style={{ color: "#888", fontSize: 12 }}>形态</div>
          {pattern ? (
            <Tag color={pattern.latest.confidence > 0.5 ? "red" : "default"}>
              {pattern.latest.name} ({(pattern.latest.confidence * 100).toFixed(0)}%)
            </Tag>
          ) : (
            "-"
          )}
        </div>
      </div>
      {pattern?.latest.description && (
        <div style={{ marginTop: 8, color: "#666", fontSize: 12 }}>
          {pattern.latest.description}
        </div>
      )}
    </Card>
  );
}
