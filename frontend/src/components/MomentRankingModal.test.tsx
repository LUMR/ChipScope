import { it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import MomentRankingModal from "./MomentRankingModal";
import type { Ranking } from "../api/market";

beforeEach(() => {
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

const ranking: Ranking = {
  time: "10:42",
  gainers: [{ secucode: "600519.SH", name: "贵州茅台", price: 1685, pct: 5.2 }],
  losers: [{ secucode: "601318.SH", name: "中国平安", price: 45, pct: -3.1 }],
};

it("clicking a row code fires onPickStock", () => {
  let picked = "";
  render(
    <MomentRankingModal ranking={ranking} open onClose={() => {}} onPickStock={(s) => (picked = s)} />,
  );
  fireEvent.click(screen.getByText("600519.SH"));
  expect(picked).toBe("600519.SH");
});
