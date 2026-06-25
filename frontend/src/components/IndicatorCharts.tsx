import { useEffect, useState } from "react";
import { Card, Col, Row } from "antd";
import ReactECharts from "echarts-for-react";
import { apiGet } from "../api/client";

interface Pt {
  date: string;
  close: number;
  dif: number;
  dea: number;
  hist: number;
  k: number;
  d: number;
  j: number;
  wr: number;
  rsi: number;
}

function pane(title: string, xs: string[], series: object[]) {
  return (
    <Card size="small" title={title} styles={{ body: { height: 180 } }}>
      <ReactECharts
        style={{ height: 160 }}
        option={{
          tooltip: { trigger: "axis" },
          xAxis: {
            type: "category",
            data: xs,
            axisLabel: { show: false },
          },
          yAxis: { type: "value", scale: true },
          legend: { top: 0, textStyle: { fontSize: 10 } },
          series,
        }}
      />
    </Card>
  );
}

export default function IndicatorCharts({ secucode }: { secucode: string }) {
  const [pts, setPts] = useState<Pt[]>([]);
  useEffect(() => {
    let cancel = false;
    apiGet<Pt[]>(`/stocks/${secucode}/indicators`, { count: "60" })
      .then((d) => {
        if (!cancel) setPts(d);
      })
      .catch(() => {
        if (!cancel) setPts([]);
      });
    return () => {
      cancel = true;
    };
  }, [secucode]);

  if (!pts.length) return null;

  const xs = pts.map((p) => p.date);
  const line = (key: keyof Pt, color: string) => ({
    name: key.toString().toUpperCase(),
    type: "line" as const,
    data: pts.map((p) => p[key] as number),
    showSymbol: false,
    lineStyle: { width: 1.2, color },
  });

  return (
    <Row gutter={[8, 8]} style={{ marginTop: 8 }}>
      <Col span={12}>
        {pane("MACD", xs, [
          { ...line("dif", "#f5222d") },
          { ...line("dea", "#16a34a") },
          { name: "HIST", type: "bar", data: pts.map((p) => p.hist) },
        ])}
      </Col>
      <Col span={12}>
        {pane("KDJ", xs, [
          { ...line("k", "#f5222d") },
          { ...line("d", "#16a34a") },
          { ...line("j", "#5b6cff") },
        ])}
      </Col>
      <Col span={12}>{pane("WR", xs, [line("wr", "#5b6cff")])}</Col>
      <Col span={12}>{pane("RSI", xs, [line("rsi", "#5b6cff")])}</Col>
    </Row>
  );
}
