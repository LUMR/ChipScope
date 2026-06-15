import { AutoComplete, Input, Popconfirm, Typography } from "antd";
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { listStocks } from "../api/stocks";
import { useWatchlist } from "../hooks/useWatchlist";
import { useQuote } from "../hooks/useRealtimeQuotes";
import type { Stock } from "../types/domain";

const { Text } = Typography;

export default function SiderWatchlist() {
  const nav = useNavigate();
  const { secucode: active } = useParams();
  const { items, add, remove } = useWatchlist();
  const [text, setText] = useState("");
  const [opts, setOpts] = useState<{ value: string; label: string }[]>([]);

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
    <div style={{ padding: 12 }}>
      <Text type="secondary" style={{ fontSize: 12 }}>
        自选股 ({items.length})
      </Text>
      <div style={{ marginTop: 8 }}>
        {items.map((w) => (
          <WatchRow
            key={w.secucode}
            secucode={w.secucode}
            name={w.name}
            active={w.secucode === active}
            onClick={() => nav(`/stock/${w.secucode}`)}
            onRemove={() => remove(w.secucode)}
          />
        ))}
      </div>
      <AutoComplete
        style={{ width: "100%", marginTop: 12 }}
        options={opts}
        value={text}
        onChange={setText}
        onSelect={async (val: string) => {
          setText("");
          await add(val);
          nav(`/stock/${val}`);
        }}
      >
        <Input.Search placeholder="+ 添加自选" />
      </AutoComplete>
    </div>
  );
}

function WatchRow({
  secucode,
  name,
  active,
  onClick,
  onRemove,
}: {
  secucode: string;
  name: string;
  active: boolean;
  onClick: () => void;
  onRemove: () => void;
}) {
  const quote = useQuote(secucode);
  const price = quote?.price;
  return (
    <div
      onClick={onClick}
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "6px 8px",
        borderRadius: 6,
        cursor: "pointer",
        background: active ? "#eef2ff" : "transparent",
        fontWeight: active ? 600 : 400,
      }}
      className="watch-row"
    >
      <span style={{ fontSize: 13 }}>{name}</span>
      <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
        {price != null && (
          <span
            style={{
              fontSize: 12,
              fontFamily: "ui-monospace, monospace",
              color: "#374151",
            }}
          >
            {price.toFixed(2)}
          </span>
        )}
        <Popconfirm
          title="移出自选？"
          onConfirm={onRemove}
          okText="移出"
          cancelText="取消"
        >
          <span
            onClick={(e) => e.stopPropagation()}
            style={{ display: "none", color: "#9ca3af", cursor: "pointer" }}
            className="watch-row-del"
          >
            ×
          </span>
        </Popconfirm>
      </span>
    </div>
  );
}
