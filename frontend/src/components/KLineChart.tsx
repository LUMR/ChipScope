import ReactECharts from "echarts-for-react";
import type { KlineBar } from "../types/domain";
import { ma } from "../utils/format";

export default function KLineChart({ bars }: { bars: KlineBar[] }) {
  if (bars.length === 0) return <div style={{ padding: 16 }}>无 K 线数据</div>;
  const dates = bars.map((b) => b.ts.slice(0, 10));
  // ECharts candlestick: [open, close, low, high]
  const ohlc = bars.map((b) => [b.open, b.close, b.low, b.high]);
  const closes = bars.map((b) => b.close);
  const option = {
    xAxis: { type: "category", data: dates },
    yAxis: { type: "value", scale: true },
    legend: { data: ["日K", "MA5", "MA20"] },
    dataZoom: [{ type: "inside" }, { type: "slider" }],
    series: [
      { name: "日K", type: "candlestick", data: ohlc },
      {
        name: "MA5",
        type: "line",
        data: ma(closes, 5),
        smooth: true,
        lineStyle: { width: 1 },
        showSymbol: false,
      },
      {
        name: "MA20",
        type: "line",
        data: ma(closes, 20),
        smooth: true,
        lineStyle: { width: 1 },
        showSymbol: false,
      },
    ],
    tooltip: { trigger: "axis" },
  };
  return <ReactECharts option={option} style={{ height: 360 }} />;
}
