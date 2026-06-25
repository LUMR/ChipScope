import { AutoComplete, Input, Menu } from "antd";
import { useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { useStockSearch } from "../hooks/useStockSearch";

export default function TopNav() {
  const nav = useNavigate();
  const loc = useLocation();
  const [text, setText] = useState("");
  const opts = useStockSearch(text);

  const activeKey = loc.pathname.startsWith("/watchlist")
    ? "watchlist"
    : loc.pathname.startsWith("/archive")
    ? "archive"
    : loc.pathname.startsWith("/market")
    ? "minute"
    : loc.pathname.startsWith("/screener")
    ? "screener"
    : "market";

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 24, height: "100%" }}>
      <strong style={{ color: "#5b6cff", fontSize: 18 }}>◣ ChipScope</strong>
      <Menu
        mode="horizontal"
        selectedKeys={[activeKey]}
        style={{ flex: 1, borderBottom: "none" }}
        items={[
          { key: "market", label: "自选行情", onClick: () => nav("/") },
          { key: "minute", label: "行情", onClick: () => nav("/market") },
          { key: "screener", label: "选股", onClick: () => nav("/screener") },
          { key: "watchlist", label: "自选管理", onClick: () => nav("/watchlist") },
          { key: "archive", label: "数据存档", onClick: () => nav("/archive") },
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
