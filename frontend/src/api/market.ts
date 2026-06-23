import { apiGet } from "./client";

export interface OverviewPoint {
  t: string;
  avg_pct: number | null;
  up: number;
  limit_up: number;
  flat: number;
  down: number;
  limit_down: number;
}

export interface OverviewSummary {
  total: number;
  with_pre_close: number;
  up: number;
  limit_up: number;
  flat: number;
  down: number;
  limit_down: number;
}

export interface Overview {
  trade_date: string;
  series: OverviewPoint[];
  summary: OverviewSummary;
}

export interface RankItem {
  secucode: string;
  name: string;
  price: number;
  pct: number;
}

export interface Ranking {
  time: string;
  gainers: RankItem[];
  losers: RankItem[];
}

export interface StockMinutePoint {
  t: string;
  price: number;
  vol: number;
  pct: number | null;
}

export interface StockMinute {
  secucode: string;
  name: string;
  pre_close: number | null;
  points: StockMinutePoint[];
}

export const getMarketDates = () => apiGet<string[]>("/market/minute/dates");
export const getMarketOverview = (date: string) =>
  apiGet<Overview>("/market/minute/overview", { date });
export const getMarketRanking = (date: string, time: string) =>
  apiGet<Ranking>("/market/minute/ranking", { date, time });
export const getStockMinute = (date: string, secucode: string) =>
  apiGet<StockMinute>("/market/minute/stock", { date, secucode });
