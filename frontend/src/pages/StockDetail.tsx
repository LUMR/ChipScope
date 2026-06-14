import { useEffect, useState } from "react";
import { Alert, Layout, Spin } from "antd";
import { useParams } from "react-router-dom";
import ChipFlame from "../components/ChipFlame";
import DateSlider from "../components/DateSlider";
import Header from "../components/Header";
import KLineChart from "../components/KLineChart";
import MetricPanel from "../components/MetricPanel";
import Watchlist from "../components/Watchlist";
import { getChips } from "../api/stocks";
import { useStockData } from "../hooks/useStockData";
import type { ChipDistribution } from "../types/domain";

const { Header: AntHeader, Sider, Content } = Layout;

export default function StockDetail() {
  const { secucode = "600519.SH" } = useParams();
  const { kline, pattern, loading, error } = useStockData(secucode);
  const [dateIdx, setDateIdx] = useState(0);
  const [chip, setChip] = useState<ChipDistribution | undefined>();

  const dates = kline.map((k) => k.ts.slice(0, 10));

  // 切股时跳到最新日期
  useEffect(() => {
    setDateIdx(Math.max(0, dates.length - 1));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [secucode]);

  // 滑块日期对应的筹码
  useEffect(() => {
    if (dates.length === 0) {
      setChip(undefined);
      return;
    }
    const d = dates[dateIdx];
    let cancelled = false;
    getChips(secucode, d)
      .then((rows) => {
        if (!cancelled) setChip(rows[0]);
      })
      .catch(() => {
        if (!cancelled) setChip(undefined);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [secucode, dateIdx, dates.length]);

  return (
    <Layout style={{ minHeight: "100vh" }}>
      <AntHeader style={{ background: "#fff", padding: "0 16px" }}>
        <Header />
      </AntHeader>
      <Layout>
        <Sider width={180} theme="light">
          <Watchlist />
        </Sider>
        <Content style={{ padding: 16 }}>
          {loading ? (
            <Spin />
          ) : error ? (
            <Alert type="error" message={error} />
          ) : (
            <>
              <KLineChart bars={kline} />
              <DateSlider dates={dates} value={dateIdx} onChange={setDateIdx} />
              <ChipFlame chip={chip} />
              <div style={{ marginTop: 16 }}>
                <MetricPanel chip={chip} pattern={pattern} />
              </div>
            </>
          )}
        </Content>
      </Layout>
    </Layout>
  );
}
