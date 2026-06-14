import { useEffect, useState } from "react";
import { getKline, getPattern } from "../api/stocks";
import type { KlineBar, PatternResult } from "../types/domain";

export function useStockData(secucode: string) {
  const [kline, setKline] = useState<KlineBar[]>([]);
  const [pattern, setPattern] = useState<PatternResult | undefined>();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | undefined>();

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(undefined);
    Promise.all([getKline(secucode), getPattern(secucode)])
      .then(([k, p]) => {
        if (cancelled) return;
        setKline(k);
        setPattern(p);
      })
      .catch((e) => {
        if (!cancelled) setError(String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [secucode]);

  return { kline, pattern, loading, error };
}
