import { apiGet } from "./client";
import type {
  ChipDistribution,
  KlineBar,
  PatternResult,
  Stock,
} from "../types/domain";

export const listStocks = (q?: string) =>
  apiGet<Stock[]>("/stocks", q ? { q } : undefined);

export const getKline = (secucode: string) =>
  apiGet<KlineBar[]>(`/stocks/${secucode}/kline`);

export const getChips = (secucode: string, date?: string) =>
  apiGet<ChipDistribution[]>(
    `/stocks/${secucode}/chips`,
    date ? { date } : undefined
  );

export const getPattern = (secucode: string) =>
  apiGet<PatternResult>(`/stocks/${secucode}/pattern`);
