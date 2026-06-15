import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

/**
 * 自选股报价，走 WebSocket /ws/realtime（全局订阅：单连接收所有自选股推送）。
 *
 * scheduler 已嵌入 uvicorn 同进程，realtime_loop 每 3s 调 broadcast_global，
 * 直达本连接——无需轮询。断线指数退避重连（1s 起，上限 15s）。
 */
type QuoteEntry = {
  price: number | null;
  pct_change: number | null;
};
type QuoteMap = Record<string, QuoteEntry>;

const QuoteContext = createContext<QuoteMap>({});

function wsUrl() {
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${window.location.host}/ws/realtime`;
}

export function RealtimeProvider({ children }: { children: ReactNode }) {
  const [quotes, setQuotes] = useState<QuoteMap>({});

  useEffect(() => {
    let retry = 1000;
    let closed = false;
    let timer: ReturnType<typeof setTimeout>;
    let ws: WebSocket | undefined;

    const connect = () => {
      ws = new WebSocket(wsUrl());
      ws.onopen = () => {
        retry = 1000; // 连接成功后重置退避到基线
      };
      ws.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data) as {
            secucode?: string;
            price?: number | null;
            pct_change?: number | null;
          };
          const secucode = data.secucode;
          if (!secucode) return;
          setQuotes((prev) => ({
            ...prev,
            [secucode]: {
              price: data.price ?? null,
              pct_change: data.pct_change ?? null,
            },
          }));
        } catch {
          /* ignore malformed */
        }
      };
      ws.onclose = () => {
        if (closed) return;
        timer = setTimeout(connect, retry);
        retry = Math.min(retry * 2, 15000); // 指数退避，上限 15s
      };
    };
    connect();
    return () => {
      closed = true;
      clearTimeout(timer);
      ws?.close();
    };
  }, []);

  return (
    <QuoteContext.Provider value={quotes}>{children}</QuoteContext.Provider>
  );
}

export function useQuote(secucode: string): QuoteEntry | undefined {
  return useContext(QuoteContext)[secucode];
}

export function useAllQuotes(): QuoteMap {
  return useContext(QuoteContext);
}
