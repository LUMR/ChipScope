import { describe, expect, it, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { RealtimeProvider, useQuote, useAllQuotes } from "./useRealtimeQuotes";
import type { ReactNode } from "react";
import type { WatchlistItem } from "../types/domain";

vi.mock("../api/watchlist", () => ({
  getWatchlist: vi.fn(),
  addWatchlist: vi.fn(),
  removeWatchlist: vi.fn(),
  reorderWatchlist: vi.fn(),
}));

import { getWatchlist } from "../api/watchlist";

const item = (
  secucode: string,
  price: number | null,
  pct: number | null
): WatchlistItem => ({
  secucode,
  code: secucode.split(".")[0],
  name: secucode,
  industry: null,
  sort_order: 0,
  created_at: "2026-06-15T00:00:00Z",
  price,
  pct_change: pct,
});

beforeEach(() => vi.clearAllMocks());

const wrapper = ({ children }: { children: ReactNode }) => (
  <RealtimeProvider>{children}</RealtimeProvider>
);

describe("useRealtimeQuotes", () => {
  it("polls /api/watchlist and maps price/pct_change by secucode", async () => {
    vi.mocked(getWatchlist).mockResolvedValue([
      item("600519.SH", 1689.5, 2.3),
      item("000001.SZ", 11.2, -0.5),
    ]);

    const { result } = renderHook(
      () => ({ q: useQuote("600519.SH"), all: useAllQuotes() }),
      { wrapper }
    );

    // mount 即触发首次 poll
    await waitFor(() => expect(result.current.q?.price).toBe(1689.5));
    expect(result.current.q?.pct_change).toBe(2.3);
    expect(Object.keys(result.current.all)).toHaveLength(2);
    expect(getWatchlist).toHaveBeenCalled();
  });
});
