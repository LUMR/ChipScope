import { useEffect, useState } from "react";
import { listStocks } from "../api/stocks";
import type { Stock } from "../types/domain";

export interface SearchOption {
  value: string; // secucode
  label: string;
}

export function useStockSearch(text: string): SearchOption[] {
  const [options, setOptions] = useState<SearchOption[]>([]);
  useEffect(() => {
    if (!text) {
      setOptions([]);
      return;
    }
    let cancelled = false;
    listStocks(text)
      .then((stocks: Stock[]) => {
        if (cancelled) return;
        setOptions(
          stocks.map((s) => ({ value: s.secucode, label: `${s.name} ${s.code}` }))
        );
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [text]);
  return options;
}
