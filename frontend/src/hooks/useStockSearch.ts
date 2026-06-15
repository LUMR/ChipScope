import { useEffect, useState } from "react";
import { message } from "antd";
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
      .catch((e) => {
        console.error("stock search failed", e);
        message.error("搜索失败，请稍后重试");
      });
    return () => {
      cancelled = true;
    };
  }, [text]);
  return options;
}
