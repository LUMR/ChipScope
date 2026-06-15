import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import {
  addWatchlist,
  getWatchlist,
  removeWatchlist,
  reorderWatchlist,
} from "../api/watchlist";
import type { WatchlistItem } from "../types/domain";

export interface WatchlistState {
  items: WatchlistItem[];
  loading: boolean;
  add: (secucode: string) => Promise<void>;
  remove: (secucode: string) => Promise<void>;
  reorder: (secucodes: string[]) => Promise<void>;
  reload: () => Promise<void>;
}

const WatchlistContext = createContext<WatchlistState | null>(null);

export function WatchlistProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<WatchlistItem[]>([]);
  const [loading, setLoading] = useState(true);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      setItems(await getWatchlist());
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  const add = useCallback(async (secucode: string) => {
    await addWatchlist(secucode);
    await reload();
  }, [reload]);

  const remove = useCallback(async (secucode: string) => {
    const prev = items;
    setItems((cur) => cur.filter((i) => i.secucode !== secucode));
    try {
      await removeWatchlist(secucode);
    } catch {
      setItems(prev); // 回滚
    }
  }, [items]);

  const reorder = useCallback(async (secucodes: string[]) => {
    const prev = items;
    const map = new Map(prev.map((i) => [i.secucode, i]));
    setItems(secucodes.map((s) => map.get(s)!).filter(Boolean));
    try {
      await reorderWatchlist(secucodes);
    } catch {
      setItems(prev);
    }
  }, [items]);

  const value: WatchlistState = { items, loading, add, remove, reorder, reload };

  return (
    <WatchlistContext.Provider value={value}>
      {children}
    </WatchlistContext.Provider>
  );
}

export function useWatchlist(): WatchlistState {
  const ctx = useContext(WatchlistContext);
  if (!ctx) {
    throw new Error("useWatchlist must be used within a WatchlistProvider");
  }
  return ctx;
}
