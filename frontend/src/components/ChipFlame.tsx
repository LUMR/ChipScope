import ReactECharts from "echarts-for-react";
import type { ChipDistribution } from "../types/domain";

/**
 * 筹码火焰图（横向）：Y 轴价格、X 轴占比，颜色深浅映射筹码量（红多）。
 */
export default function ChipFlame({ chip }: { chip?: ChipDistribution }) {
  if (!chip) return <div style={{ padding: 16 }}>无筹码数据</div>;
  const entries = Object.entries(chip.distribution)
    .map(([price, ratio]) => ({ price: Number(price), ratio }))
    .sort((a, b) => a.price - b.price);
  const prices = entries.map((e) => e.price.toFixed(2));
  const ratios = entries.map((e) => e.ratio);
  const maxRatio = Math.max(...ratios, 1e-9);
  const option = {
    grid: { left: 60, right: 30, top: 20, bottom: 30 },
    xAxis: {
      type: "value",
      name: "占比",
      axisLabel: {
        formatter: (v: number) => `${(v * 100).toFixed(0)}%`,
      },
    },
    yAxis: { type: "category", data: prices, inverse: true },
    series: [
      {
        type: "bar",
        data: ratios,
        itemStyle: {
          color: (p: { value: number }) =>
            `rgba(220,40,40,${0.2 + 0.8 * (p.value / maxRatio)})`,
        },
      },
    ],
    tooltip: {
      trigger: "axis",
      formatter: (xs: { name: string; value: number }[]) =>
        `${xs[0].name}<br/>占比 ${(xs[0].value * 100).toFixed(2)}%`,
    },
  };
  return <ReactECharts option={option} style={{ height: 400 }} />;
}
