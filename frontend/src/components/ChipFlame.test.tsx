import { describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/react";
import type { ChipDistribution } from "../types/domain";

// vi.hoisted 保证 holder 在 vi.mock 提升后仍可用，捕获传给 ECharts 的 option
const { optionHolder } = vi.hoisted(() => ({ optionHolder: { option: null as unknown } }));

vi.mock("echarts-for-react", () => ({
  default: (props: { option: unknown }) => {
    optionHolder.option = props.option;
    return null;
  },
}));

import ChipFlame from "./ChipFlame";

const chip: ChipDistribution = {
  ts: "2026-06-17T00:00:00Z",
  distribution: { "30.00": 0.3, "10.00": 0.2, "20.00": 0.5 }, // 故意乱序，验证排序
  concentration: 0.5,
  cost_high: 30,
  cost_low: 10,
  profit_ratio: 0.5,
  avg_cost: 20,
};

describe("ChipFlame", () => {
  it("y 轴价格升序、不反转：最低价在底部、最高价在顶部", () => {
    render(<ChipFlame chip={chip} />);
    const option = optionHolder.option as {
      yAxis: { data: string[]; inverse?: boolean };
    };
    // data 升序（低价在前）
    expect(option.yAxis.data).toEqual(["10.00", "20.00", "30.00"]);
    // inverse=true 会把最低价翻到顶部，造成 y 轴数值倒置——不该为 true
    expect(option.yAxis.inverse).toBeFalsy();
  });
});
