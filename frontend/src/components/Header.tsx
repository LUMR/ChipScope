import { AutoComplete, Input } from "antd";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { listStocks } from "../api/stocks";
import type { Stock } from "../types/domain";

export default function Header() {
  const nav = useNavigate();
  const [opts, setOpts] = useState<{ value: string; label: string }[]>([]);
  const [text, setText] = useState("");

  useEffect(() => {
    if (!text) {
      setOpts([]);
      return;
    }
    let cancelled = false;
    listStocks(text)
      .then((stocks: Stock[]) => {
        if (cancelled) return;
        setOpts(
          stocks.map((s) => ({ value: s.secucode, label: `${s.name} ${s.code}` }))
        );
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [text]);

  return (
    <AutoComplete
      style={{ width: 320 }}
      options={opts}
      value={text}
      onChange={setText}
      onSelect={(val: string) => nav(`/stock/${val}`)}
    >
      <Input.Search placeholder="搜索股票代码/名称" />
    </AutoComplete>
  );
}
