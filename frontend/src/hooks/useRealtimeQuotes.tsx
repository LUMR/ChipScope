import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { getWatchlist } from "../api/watchlist";

/**
 * 自选股报价。
 *
 * 原设计走 WebSocket，但 scheduler 与 uvicorn 是两个独立进程，
 * ConnectionManager 单例不跨进程，scheduler 的 broadcast 推不到 uvicorn 的
 * WS 客户端。改为轮询 GET /api/watchlist（读 Redis 缓存，scheduler 每 3s 刷新），
 * 准实时且跨进程可靠。
 */
type QuoteEntry = {
  price: number | null;
  pct_change: number | null;
};
type QuoteMap = Record<string, QuoteEntry>;

const QuoteContext = createContext<QuoteMap>({});

const POLL_MS = 3000;

export function RealtimeProvider({ children }: { children: ReactNode }) {
  const [quotes, setQuotes] = useState<QuoteMap>({});

  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const items = await getWatchlist();
        if (cancelled) return;
        const map: QuoteMap = {};
        for (const it of items) {
          map[it.secucode] = { price: it.price, pct_change: it.pct_change };
        }
        setQuotes(map);
      } catch {
        /* 瞬时错误忽略，下一轮重试 */
      }
    };
    poll();
    const id = setInterval(poll, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
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
