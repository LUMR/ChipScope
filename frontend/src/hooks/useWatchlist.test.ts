import { describe, expect, it, vi, beforeEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { useWatchlist } from "./useWatchlist";

vi.mock("../api/watchlist", () => ({
  getWatchlist: vi.fn(),
  addWatchlist: vi.fn(),
  removeWatchlist: vi.fn(),
  reorderWatchlist: vi.fn(),
}));

import { getWatchlist, addWatchlist, removeWatchlist, reorderWatchlist } from "../api/watchlist";

const ITEM = (secucode: string, sort_order: number) => ({
  secucode, code: secucode.split(".")[0], name: secucode, industry: null,
  sort_order, created_at: "2026-06-15T00:00:00Z", price: null, pct_change: null,
});

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getWatchlist).mockResolvedValue([ITEM("600519.SH", 0), ITEM("000001.SZ", 1)]);
});

describe("useWatchlist", () => {
  it("loads items on mount", async () => {
    const { result } = renderHook(() => useWatchlist());
    await waitFor(() => expect(result.current.items).toHaveLength(2));
  });

  it("add reloads list", async () => {
    const { result } = renderHook(() => useWatchlist());
    await waitFor(() => expect(result.current.items).toHaveLength(2));
    vi.mocked(addWatchlist).mockResolvedValue(ITEM("000858.SZ", 2));
    vi.mocked(getWatchlist).mockResolvedValue([
      ITEM("600519.SH", 0), ITEM("000001.SZ", 1), ITEM("000858.SZ", 2),
    ]);
    await act(async () => { await result.current.add("000858.SZ"); });
    await waitFor(() => expect(result.current.items).toHaveLength(3));
    expect(addWatchlist).toHaveBeenCalledWith("000858.SZ");
  });

  it("remove does optimistic delete + persists", async () => {
    const { result } = renderHook(() => useWatchlist());
    await waitFor(() => expect(result.current.items).toHaveLength(2));
    vi.mocked(removeWatchlist).mockResolvedValue(undefined);
    await act(async () => { await result.current.remove("600519.SH"); });
    expect(removeWatchlist).toHaveBeenCalledWith("600519.SH");
    await waitFor(() =>
      expect(result.current.items.find((i) => i.secucode === "600519.SH")).toBeUndefined()
    );
  });

  it("reorder persists new order", async () => {
    const { result } = renderHook(() => useWatchlist());
    await waitFor(() => expect(result.current.items).toHaveLength(2));
    vi.mocked(reorderWatchlist).mockResolvedValue(undefined);
    await act(async () => {
      await result.current.reorder(["000001.SZ", "600519.SH"]);
    });
    expect(reorderWatchlist).toHaveBeenCalledWith(["000001.SZ", "600519.SH"]);
  });
});
