import { useState } from "react";
import { Button, Checkbox, Select, Space, Table, Typography, message } from "antd";
import type { ColumnsType } from "antd/es/table";
import { useNavigate } from "react-router-dom";
import { screenStocks, type ExtraCondition, type ScreenItem } from "../api/screener";

const { Text } = Typography;

const SIGNALS = ["strong_bull", "bull", "neutral", "bear", "strong_bear"] as const;
const SIGNAL_LABEL: Record<string, string> = {
  strong_bull: "强多",
  bull: "偏多",
  neutral: "中性",
  bear: "偏空",
  strong_bear: "强空",
};

const EXTRA_KEYS = ["ma_bull", "breakout", "volume_up"] as const;
type ExtraKey = (typeof EXTRA_KEYS)[number];

const EXTRA_LABEL: Record<ExtraKey, string> = {
  ma_bull: "均线多头",
  breakout: "突破20日",
  volume_up: "放量",
};

function Arrow({ v }: { v: number }) {
  const color = v > 0 ? "#f5222d" : v < 0 ? "#16a34a" : "#9ca3af";
  const sym = v > 0 ? "▲" : v < 0 ? "▼" : "—";
  return <span style={{ color }}>{sym}</span>;
}

export default function ScreenerPage() {
  const [signal, setSignal] = useState<string>("strong_bull");
  const [extras, setExtras] = useState<Record<ExtraKey, boolean>>({
    ma_bull: false,
    breakout: false,
    volume_up: false,
  });
  const [data, setData] = useState<ScreenItem[]>([]);
  const [loading, setLoading] = useState(false);
  const nav = useNavigate();

  const run = async () => {
    setLoading(true);
    try {
      const ex: ExtraCondition[] = EXTRA_KEYS.filter((k) => extras[k]).map((k) =>
        k === "breakout" ? { type: "breakout", n: 20 } : { type: k }
      );
      setData(await screenStocks({ signal, extras: ex }));
    } catch (e: unknown) {
      message.error(String((e as Error | undefined)?.message ?? e));
    } finally {
      setLoading(false);
    }
  };

  const columns: ColumnsType<ScreenItem> = [
    {
      title: "代码",
      dataIndex: "secucode",
      render: (v: string) => (
        <a onClick={() => nav(`/stock/${v}`)}>{v}</a>
      ),
    },
    { title: "名称", dataIndex: "name" },
    {
      title: "现价",
      dataIndex: "close",
      align: "right",
      render: (v: number) => v.toFixed(2),
    },
    {
      title: "涨幅",
      dataIndex: "pct",
      align: "right",
      render: (v: number) => `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`,
    },
    {
      title: "综合分",
      dataIndex: "score",
      align: "right",
      sorter: (a, b) => a.score - b.score,
      defaultSortOrder: "descend",
      render: (v: number) => <Text strong>{v}</Text>,
    },
    {
      title: "信号",
      dataIndex: "signal",
      render: (v: string) => SIGNAL_LABEL[v] ?? v,
    },
    {
      title: "MACD",
      dataIndex: "macd",
      align: "center",
      render: (v: number) => <Arrow v={v} />,
    },
    {
      title: "KDJ",
      dataIndex: "kdj",
      align: "center",
      render: (v: number) => <Arrow v={v} />,
    },
    {
      title: "WR",
      dataIndex: "wr",
      align: "center",
      render: (v: number) => <Arrow v={v} />,
    },
    {
      title: "RSI",
      dataIndex: "rsi",
      align: "center",
      render: (v: number) => <Arrow v={v} />,
    },
  ];

  return (
    <Space direction="vertical" style={{ width: "100%" }}>
      <Space wrap>
        <Select
          value={signal}
          onChange={setSignal}
          style={{ width: 120 }}
          options={SIGNALS.map((s) => ({ value: s, label: SIGNAL_LABEL[s] }))}
        />
        {EXTRA_KEYS.map((k) => (
          <Checkbox
            key={k}
            checked={extras[k]}
            onChange={(e) => setExtras({ ...extras, [k]: e.target.checked })}
          >
            {EXTRA_LABEL[k]}
          </Checkbox>
        ))}
        <Button type="primary" loading={loading} onClick={run}>
          筛选
        </Button>
      </Space>
      <Table
        size="small"
        rowKey="secucode"
        columns={columns}
        dataSource={data}
        pagination={{ pageSize: 50 }}
      />
    </Space>
  );
}
