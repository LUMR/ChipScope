import { describe, expect, it, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { message } from "antd";
import { useStockSearch } from "./useStockSearch";

vi.mock("../api/stocks", () => ({
  listStocks: vi.fn(),
}));

import { listStocks } from "../api/stocks";

beforeEach(() => {
  vi.clearAllMocks();
});

describe("useStockSearch", () => {
  it("成功时返回候选项", async () => {
    vi.mocked(listStocks).mockResolvedValue([
      { secucode: "600519.SH", code: "600519", name: "贵州茅台", market: "SH" },
    ]);
    const { result } = renderHook(() => useStockSearch("茅台"));
    await waitFor(() => expect(result.current).toHaveLength(1));
    expect(result.current[0].value).toBe("600519.SH");
    expect(result.current[0].label).toContain("贵州茅台");
  });

  it("失败时调用 message.error 而非静默吞错", async () => {
    vi.mocked(listStocks).mockRejectedValue(new Error("network"));
    const errorSpy = vi.spyOn(message, "error").mockReturnValue("x" as never);
    const { result } = renderHook(() => useStockSearch("茅台"));
    await waitFor(() => expect(errorSpy).toHaveBeenCalled());
    expect(result.current).toEqual([]);
    errorSpy.mockRestore();
  });
});
