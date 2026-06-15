import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { RealtimeProvider, useQuote, useAllQuotes } from "./useRealtimeQuotes";
import type { ReactNode } from "react";

class MockWS {
  static instances: MockWS[] = [];
  url: string;
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  readyState = 1;
  constructor(url: string) {
    this.url = url;
    MockWS.instances.push(this);
  }
  send() {}
  close() { this.readyState = 3; }
  emit(data: object) {
    this.onmessage?.({ data: JSON.stringify(data) });
  }
}

beforeEach(() => {
  MockWS.instances = [];
  (globalThis as unknown as { WebSocket: typeof MockWS }).WebSocket = MockWS;
});
afterEach(() => vi.clearAllMocks());

const wrapper = ({ children }: { children: ReactNode }) =>
  <RealtimeProvider>{children}</RealtimeProvider>;

describe("useRealtimeQuotes", () => {
  it("connects to /ws/realtime and routes quotes by secucode", async () => {
    // useQuote 与 useAllQuotes 必须在同一 Provider 实例下，否则 context 各自独立
    const { result } = renderHook(
      () => ({ q: useQuote("600519.SH"), all: useAllQuotes() }),
      { wrapper }
    );
    await waitFor(() => expect(MockWS.instances).toHaveLength(1));
    expect(MockWS.instances[0].url).toContain("/ws/realtime");

    MockWS.instances[0].emit({ secucode: "600519.SH", price: 1689.5 });
    await waitFor(() => expect(result.current.q?.price).toBe(1689.5));

    MockWS.instances[0].emit({ secucode: "000001.SZ", price: 11.2 });
    await waitFor(() => expect(Object.keys(result.current.all)).toHaveLength(2));
  });
});
