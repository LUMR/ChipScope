import { apiPost } from "./client";

export interface ExtraCondition {
  type: string;
  n?: number;
  k?: number;
  lo?: number;
  hi?: number;
}

export interface ScreenRequest {
  signal?: string;
  extras?: ExtraCondition[];
  sort?: string;
}

export interface ScreenItem {
  secucode: string;
  name: string;
  close: number;
  pct: number;
  score: number;
  signal: string;
  macd: number;
  kdj: number;
  wr: number;
  rsi: number;
}

export const screenStocks = (req: ScreenRequest): Promise<ScreenItem[]> =>
  apiPost<ScreenItem[]>("/screener", req);
