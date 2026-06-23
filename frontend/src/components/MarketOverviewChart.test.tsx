import { it, expect, vi } from "vitest";
import { render } from "@testing-library/react";
import type { Overview } from "../api/market";

const { propsHolder } = vi.hoisted(() => ({
  propsHolder: { onEvents: null as unknown },
}));

vi.mock("echarts-for-react", () => ({
  default: (props: Record<string, unknown>) => {
    propsHolder.onEvents = props.onEvents;
    return null;
  },
}));

import MarketOverviewChart from "./MarketOverviewChart";

const ov: Overview = {
  trade_date: "2026-06-18",
  series: [
    {
      t: "10:42",
      avg_pct: 0.5,
      up: 1,
      limit_up: 0,
      flat: 0,
      down: 1,
      limit_down: 0,
    },
  ],
  summary: {
    total: 2,
    with_pre_close: 2,
    up: 1,
    limit_up: 0,
    flat: 0,
    down: 1,
    limit_down: 0,
  },
};

it("registers a click handler that maps a line click to onPickTime", () => {
  let picked = "";
  render(
    <MarketOverviewChart
      overview={ov}
      onPickTime={(t) => {
        picked = t;
      }}
    />
  );
  (propsHolder.onEvents as Record<string, (p: { componentType: string; name: string }) => void>).click({
    componentType: "line",
    name: "10:42",
  });
  expect(picked).toBe("10:42");
});
