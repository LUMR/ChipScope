import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, waitFor } from "@testing-library/react";

// Capture the option passed to ReactECharts so we can assert series without
// relying on jest-dom matchers (project tsconfig omits @testing-library/jest-dom).
const { chartHolder } = vi.hoisted(() => ({
  chartHolder: { options: [] as unknown[] },
}));

vi.mock("echarts-for-react", () => ({
  default: (props: { option: unknown }) => {
    chartHolder.options.push(props.option);
    return null;
  },
}));

vi.mock("../api/client", () => ({
  apiGet: vi.fn(),
}));

import { apiGet } from "../api/client";
import IndicatorCharts from "./IndicatorCharts";

const sample = [
  {
    date: "2026-06-01",
    close: 100,
    dif: 1,
    dea: 0.5,
    hist: 1,
    k: 50,
    d: 50,
    j: 50,
    wr: 50,
    rsi: 50,
  },
  {
    date: "2026-06-02",
    close: 101,
    dif: 1.2,
    dea: 0.6,
    hist: 0.6,
    k: 55,
    d: 48,
    j: 69,
    wr: 40,
    rsi: 55,
  },
];

beforeEach(() => {
  vi.clearAllMocks();
  chartHolder.options = [];
  // antd Grid responsive observer needs matchMedia in jsdom
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }));
});

describe("IndicatorCharts", () => {
  it("renders four indicator panels (MACD/KDJ/WR/RSI) with the fetched series", async () => {
    vi.mocked(apiGet).mockResolvedValue(sample);

    const { getByText } = render(<IndicatorCharts secucode="600519.SH" />);

    // 四个 Card 标题都应渲染（getByText 找不到会抛错，waitFor 兜底异步）
    await waitFor(() => getByText("MACD"));
    getByText("KDJ");
    getByText("WR");
    getByText("RSI");

    // apiGet 用了正确路径与 count 参数
    expect(vi.mocked(apiGet)).toHaveBeenCalledWith(
      "/stocks/600519.SH/indicators",
      { count: "60" }
    );

    // 4 个副图各渲染一个 ECharts
    expect(chartHolder.options).toHaveLength(4);
    // MACD 面板含 dif/dea/hist 三条线/柱
    const macd = chartHolder.options[0] as { series: { name: string }[] };
    const macdNames = macd.series.map((s) => s.name);
    expect(macdNames).toEqual(["DIF", "DEA", "HIST"]);
    // KDJ 含 K/D/J
    const kdj = chartHolder.options[1] as { series: { name: string }[] };
    expect(kdj.series.map((s) => s.name)).toEqual(["K", "D", "J"]);
    // WR 单线
    const wr = chartHolder.options[2] as { series: { name: string }[] };
    expect(wr.series.map((s) => s.name)).toEqual(["WR"]);
    // RSI 单线
    const rsi = chartHolder.options[3] as { series: { name: string }[] };
    expect(rsi.series.map((s) => s.name)).toEqual(["RSI"]);
  });

  it("renders nothing while data is empty", async () => {
    vi.mocked(apiGet).mockResolvedValue([]);

    const { container } = render(<IndicatorCharts secucode="000001.SZ" />);
    // 空数据返回 null → 不渲染任何 Card / 图表
    expect(chartHolder.options).toHaveLength(0);
    expect(container.firstChild).toBeNull();
  });

  it("refetches when secucode changes", async () => {
    vi.mocked(apiGet).mockResolvedValue(sample);

    const { rerender, getByText } = render(
      <IndicatorCharts secucode="600519.SH" />
    );
    await waitFor(() => getByText("MACD"));

    vi.mocked(apiGet).mockClear();
    rerender(<IndicatorCharts secucode="000001.SZ" />);
    await waitFor(() =>
      expect(vi.mocked(apiGet)).toHaveBeenCalledWith(
        "/stocks/000001.SZ/indicators",
        { count: "60" }
      )
    );
  });
});
