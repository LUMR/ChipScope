import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import type { RealtimeQuote } from "../types/domain";

type QuoteMap = Record<string, RealtimeQuote>;

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
    let ws: WebSocket;

    const connect = () => {
      ws = new WebSocket(wsUrl());
      ws.onopen = () => {
        retry = 1000; // 连接成功后重置退避到基线
      };
      ws.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data) as RealtimeQuote;
          if (data.secucode) {
            setQuotes((prev) => ({ ...prev, [data.secucode]: data }));
          }
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

export function useQuote(secucode: string): RealtimeQuote | undefined {
  return useContext(QuoteContext)[secucode];
}

export function useAllQuotes(): QuoteMap {
  return useContext(QuoteContext);
}
