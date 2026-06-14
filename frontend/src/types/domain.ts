export interface Stock {
  secucode: string;
  code: string;
  name: string;
  market: string;
}

export interface KlineBar {
  ts: string;
  open: number;
  close: number;
  high: number;
  low: number;
  volume: number;
  amount: number;
  turnover_rate: number;
  pct_change: number;
  vwap: number;
}

export interface ChipDistribution {
  ts: string;
  distribution: Record<string, number>; // {"15.00": 0.08}
  concentration: number;
  cost_high: number;
  cost_low: number;
  profit_ratio: number;
  avg_cost: number;
}

export interface PatternForm {
  name: string;
  confidence: number;
  description: string;
}

export interface PatternResult {
  latest: PatternForm;
  trend: PatternForm;
  current_price: number;
}
