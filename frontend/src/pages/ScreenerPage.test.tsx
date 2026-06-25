import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { message } from "antd";

vi.mock("../api/screener", () => ({
  screenStocks: vi.fn(),
}));

import { screenStocks } from "../api/screener";
import ScreenerPage from "./ScreenerPage";

beforeEach(() => {
  vi.clearAllMocks();
  // antd Space/Grid responsive observer needs matchMedia in jsdom
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

describe("ScreenerPage", () => {
  it("renders screener results with score and signals after running", async () => {
    vi.mocked(screenStocks).mockResolvedValue([
      {
        secucode: "600519.SH",
        name: "贵州茅台",
        close: 1680,
        pct: 1.2,
        score: 4,
        signal: "strong_bull",
        macd: 1,
        kdj: 1,
        wr: 1,
        rsi: 1,
      },
    ]);

    render(
      <MemoryRouter>
        <ScreenerPage />
      </MemoryRouter>
    );

    await userEvent.click(screen.getByRole("button", { name: /筛/ }));

    // 等待结果表出现茅台；getByText 找不到会抛错，waitFor 兜底异步渲染
    await waitFor(() => screen.getByText("贵州茅台"));
    screen.getByText("4"); // 综合分
    // 默认信号选 strong_bull → 强多（限定在结果表行内，避免与 Select 选中值歧义）
    const row = screen.getByText("贵州茅台").closest("tr") as HTMLTableRowElement;
    within(row).getByText("强多"); // 信号中文标签
    // 涨幅带 + 号与百分号
    within(row).getByText("+1.20%");
  });

  it("posts the selected signal and extras to the API", async () => {
    vi.mocked(screenStocks).mockResolvedValue([]);

    render(
      <MemoryRouter>
        <ScreenerPage />
      </MemoryRouter>
    );

    // 勾选「突破20日」辅助条件
    await userEvent.click(screen.getByLabelText("突破20日"));
    await userEvent.click(screen.getByRole("button", { name: /筛/ }));

    await waitFor(() => expect(vi.mocked(screenStocks)).toHaveBeenCalled());
    const req = vi.mocked(screenStocks).mock.calls[0][0];
    expect(req.signal).toBe("strong_bull");
    expect(req.extras).toEqual([{ type: "breakout", n: 20 }]);
  });

  it("shows an error message when the API fails", async () => {
    vi.mocked(screenStocks).mockRejectedValue(new Error("网络错误"));
    const errorSpy = vi.spyOn(message, "error").mockReturnValue("x" as never);

    render(
      <MemoryRouter>
        <ScreenerPage />
      </MemoryRouter>
    );

    await userEvent.click(screen.getByRole("button", { name: /筛/ }));
    await waitFor(() => expect(errorSpy).toHaveBeenCalled());
    errorSpy.mockRestore();
  });
});
