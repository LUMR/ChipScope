import {
  describe,
  expect,
  it,
  beforeEach,
  afterEach,
} from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { RealtimeProvider, useQuote, useAllQuotes } from "./useRealtimeQuotes";
import type { ReactNode } from "react";

/** 最小 WebSocket mock：记录回调，构造时异步触发 onopen。 */
class MockWebSocket {
  static instances: MockWebSocket[] = [];
  url: string;
  onopen: ((ev: Event) => void) | null = null;
  onmessage: ((ev: MessageEvent) => void) | null = null;
  onclose: ((ev: CloseEvent) => void) | null = null;
  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
    setTimeout(() => this.onopen?.(new Event("open")), 0);
  }
  send() {}
  close() {
    this.onclose?.(new CloseEvent("close"));
  }
}

const OriginalWebSocket = globalThis.WebSocket;

beforeEach(() => {
  MockWebSocket.instances = [];
  globalThis.WebSocket = MockWebSocket as unknown as typeof WebSocket;
});

afterEach(() => {
  globalThis.WebSocket = OriginalWebSocket;
});

const wrapper = ({ children }: { children: ReactNode }) => (
  <RealtimeProvider>{children}</RealtimeProvider>
);

/** 模拟后端推送一条消息（data 原样作为 e.data）。 */
function emit(ws: MockWebSocket, data: string) {
  act(() => {
    ws.onmessage?.({ data } as MessageEvent);
  });
}

describe("useRealtimeQuotes", () => {
  it("subscribes to /ws/realtime and maps inbound messages by secucode", async () => {
    const { result } = renderHook(
      () => ({ q: useQuote("600519.SH"), all: useAllQuotes() }),
      { wrapper }
    );

    await waitFor(() => expect(MockWebSocket.instances).toHaveLength(1));
    expect(MockWebSocket.instances[0].url).toMatch(/\/ws\/realtime$/);

    emit(
      MockWebSocket.instances[0],
      JSON.stringify({ secucode: "600519.SH", price: 1689.5, pct_change: 2.3 })
    );

    await waitFor(() => expect(result.current.q?.price).toBe(1689.5));
    expect(result.current.q?.pct_change).toBe(2.3);
    expect(Object.keys(result.current.all)).toHaveLength(1);
  });

  it("ignores malformed messages and those without secucode", async () => {
    const { result } = renderHook(
      () => ({ q: useQuote("600519.SH") }),
      { wrapper }
    );
    await waitFor(() => expect(MockWebSocket.instances).toHaveLength(1));
    const ws = MockWebSocket.instances[0];

    emit(ws, "{bad json"); // 非法 JSON → catch 忽略
    emit(ws, JSON.stringify({ price: 1 })); // 缺 secucode → 忽略

    expect(result.current.q).toBeUndefined(); // 600519.SH 从未收到有效推送
  });
});
