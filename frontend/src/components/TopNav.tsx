import { AutoComplete, Input, Menu } from "antd";
import { useEffect, useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { listStocks } from "../api/stocks";
import type { Stock } from "../types/domain";

export default function TopNav() {
  const nav = useNavigate();
  const loc = useLocation();
  const [opts, setOpts] = useState<{ value: string; label: string }[]>([]);
  const [text, setText] = useState("");

  const activeKey = loc.pathname.startsWith("/watchlist") ? "watchlist" : "market";

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
    <div style={{ display: "flex", alignItems: "center", gap: 24, height: "100%" }}>
      <strong style={{ color: "#5b6cff", fontSize: 18 }}>◣ ChipScope</strong>
      <Menu
        mode="horizontal"
        selectedKeys={[activeKey]}
        style={{ flex: 1, borderBottom: "none" }}
        items={[
          { key: "market", label: "行情", onClick: () => nav("/") },
          { key: "watchlist", label: "自选管理", onClick: () => nav("/watchlist") },
        ]}
      />
      <AutoComplete
        style={{ width: 280 }}
        options={opts}
        value={text}
        onChange={setText}
        onSelect={(val: string) => nav(`/stock/${val}`)}
      >
        <Input.Search placeholder="搜索股票代码/名称" />
      </AutoComplete>
    </div>
  );
}
