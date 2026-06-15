import { useCallback, useEffect, useState } from "react";
import {
  addWatchlist,
  getWatchlist,
  removeWatchlist,
  reorderWatchlist,
} from "../api/watchlist";
import type { WatchlistItem } from "../types/domain";

export function useWatchlist() {
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

  return { items, loading, add, remove, reorder, reload };
}
