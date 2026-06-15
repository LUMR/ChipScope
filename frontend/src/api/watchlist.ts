import { apiDelete, apiGet, apiPost, apiPut } from "./client";
import type { WatchlistItem } from "../types/domain";

export const getWatchlist = () => apiGet<WatchlistItem[]>("/watchlist");

export const addWatchlist = (secucode: string) =>
  apiPost<WatchlistItem>("/watchlist", { secucode });

export const removeWatchlist = (secucode: string) =>
  apiDelete<void>(`/watchlist/${secucode}`);

export const reorderWatchlist = (secucodes: string[]) =>
  apiPut<void>("/watchlist/reorder", { secucodes });
