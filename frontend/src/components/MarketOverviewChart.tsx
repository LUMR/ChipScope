import ReactECharts from "echarts-for-react";
import type { Overview, OverviewPoint } from "../api/market";

const COLORS: Record<keyof Pick<OverviewPoint, "limit_up" | "up" | "flat" | "down" | "limit_down">, string> = {
  limit_up: "#7f1d1d",
  up: "#f5222d",
  flat: "#9ca3af",
  down: "#16a34a",
  limit_down: "#14532d",
};

interface ClickParams {
  componentType: string;
  name: string;
}

type CountKey = keyof Pick<OverviewPoint, "limit_up" | "up" | "flat" | "down" | "limit_down">;

export default function MarketOverviewChart({
  overview,
  onPickTime,
}: {
  overview: Overview;
  onPickTime: (t: string) => void;
}) {
  const xs = overview.series.map((p) => p.t);
  const avg = overview.series.map((p) => p.avg_pct);
  const mk = (key: CountKey) =>
    overview.series.map((p) => p[key]);

  const option = {
    tooltip: { trigger: "axis", axisPointer: { type: "cross" } },
    legend: {
      data: ["平均涨跌幅", "涨停", "上涨", "平盘", "下跌", "跌停"],
      top: 0,
    },
    axisPointer: { link: [{ xAxisIndex: "all" }] },
    grid: [
      { left: 48, right: 24, top: 40, height: "55%" },
      { left: 48, right: 24, top: "72%", height: "22%" },
    ],
    xAxis: [
      { type: "category", data: xs, gridIndex: 0, axisLabel: { show: false } },
      { type: "category", data: xs, gridIndex: 1, axisLabel: { fontSize: 10 } },
    ],
    yAxis: [
      { type: "value", gridIndex: 0, axisLabel: { formatter: "{value}%" } },
      { type: "value", gridIndex: 1 },
    ],
    series: [
      {
        name: "平均涨跌幅",
        type: "line",
        xAxisIndex: 0,
        yAxisIndex: 0,
        data: avg,
        showSymbol: false,
        smooth: true,
        lineStyle: { width: 1.6 },
        itemStyle: { color: "#5b6cff" },
        markLine: {
          silent: true,
          data: [{ yAxis: 0 }],
          lineStyle: { color: "#475569" },
        },
      },
      {
        name: "涨停",
        type: "bar",
        stack: "cnt",
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: mk("limit_up"),
        itemStyle: { color: COLORS.limit_up },
      },
      {
        name: "上涨",
        type: "bar",
        stack: "cnt",
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: mk("up"),
        itemStyle: { color: COLORS.up },
      },
      {
        name: "平盘",
        type: "bar",
        stack: "cnt",
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: mk("flat"),
        itemStyle: { color: COLORS.flat },
      },
      {
        name: "下跌",
        type: "bar",
        stack: "cnt",
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: mk("down"),
        itemStyle: { color: COLORS.down },
      },
      {
        name: "跌停",
        type: "bar",
        stack: "cnt",
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: mk("limit_down"),
        itemStyle: { color: COLORS.limit_down },
      },
    ],
  };

  return (
    <ReactECharts
      option={option}
      style={{ height: 420 }}
      onEvents={{
        click: (params: ClickParams) => {
          if (
            params.componentType === "series" ||
            params.componentType === "line"
          ) {
            onPickTime(params.name);
          }
        },
      }}
    />
  );
}
