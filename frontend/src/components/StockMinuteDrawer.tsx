import { Drawer, Empty, Spin, Typography } from "antd";
import ReactECharts from "echarts-for-react";
import type { StockMinute } from "../api/market";

const { Text } = Typography;

export default function StockMinuteDrawer({
  open, data, loading, onClose,
}: {
  open: boolean;
  data: StockMinute | null;
  loading: boolean;
  onClose: () => void;
}) {
  const xs = data?.points.map((p) => p.t) ?? [];
  const prices = data?.points.map((p) => p.price) ?? [];
  const pcts = data?.points.map((p) => p.pct) ?? [];
  const option = {
    tooltip: { trigger: "axis" },
    legend: { data: ["价格", "涨幅%"] },
    xAxis: { type: "category", data: xs, axisLabel: { fontSize: 10 } },
    yAxis: [
      { type: "value", scale: true, name: "价" },
      { type: "value", name: "%" },
    ],
    series: [
      { name: "价格", type: "line", data: prices, showSymbol: false, itemStyle: { color: "#5b6cff" } },
      { name: "涨幅%", type: "line", yAxisIndex: 1, data: pcts, showSymbol: false, itemStyle: { color: "#f5222d" } },
    ],
  };
  return (
    <Drawer
      title={data ? `${data.name} · ${data.secucode}` : "个股分时"}
      open={open} onClose={onClose} width={480}
    >
      {loading && <Spin />}
      {!loading && !data && <Empty description="无分时数据" />}
      {!loading && data && (
        <>
          <Text type="secondary">昨收 {data.pre_close?.toFixed(2) ?? "-"}</Text>
          <ReactECharts option={option} style={{ height: 320, marginTop: 12 }} />
        </>
      )}
    </Drawer>
  );
}
