import { describe, it, expect, vi, beforeEach } from "vitest";
import { apiGet } from "../src/api/client";

beforeEach(() => {
  global.fetch = vi.fn();
});

describe("apiGet", () => {
  it("builds query string and parses json", async () => {
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      json: async () => [{ a: 1 }],
    });
    const r = await apiGet("/stocks", { q: "600" });
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/stocks?q=600")
    );
    expect(r).toEqual([{ a: 1 }]);
  });

  it("works without params", async () => {
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      json: async () => [],
    });
    await apiGet("/stocks");
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringMatching(/\/api\/stocks$/)
    );
  });

  it("throws on non-ok response", async () => {
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: false,
      status: 500,
    });
    await expect(apiGet("/stocks")).rejects.toThrow("500");
  });
});
