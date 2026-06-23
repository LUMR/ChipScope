import { Card, DatePicker, Empty, message, Space, Spin, Typography } from "antd";
import dayjs, { Dayjs } from "dayjs";
import { useEffect, useState } from "react";
import {
  getMarketDates,
  getMarketOverview,
  getMarketRanking,
  getStockMinute,
  type Overview,
  type Ranking,
  type StockMinute,
} from "../api/market";
import MarketOverviewChart from "../components/MarketOverviewChart";
import MomentRankingModal from "../components/MomentRankingModal";
import StockMinuteDrawer from "../components/StockMinuteDrawer";

const { Text, Title } = Typography;

export default function MarketMinutePage() {
  const [dates, setDates] = useState<string[]>([]);
  const [date, setDate] = useState<Dayjs | null>(null);
  const [overview, setOverview] = useState<Overview | null>(null);
  const [loading, setLoading] = useState(false);

  const [ranking, setRanking] = useState<Ranking | null>(null);
  const [rankOpen, setRankOpen] = useState(false);

  const [stock, setStock] = useState<StockMinute | null>(null);
  const [stockOpen, setStockOpen] = useState(false);
  const [stockLoading, setStockLoading] = useState(false);

  useEffect(() => {
    getMarketDates().then((ds) => {
      setDates(ds);
      if (ds.length) setDate(dayjs(ds[0]));
    }).catch(() => message.error("加载可用交易日失败"));
  }, []);

  useEffect(() => {
    if (!date) return;
    setLoading(true);
    setOverview(null);
    getMarketOverview(date.format("YYYY-MM-DD"))
      .then(setOverview)
      .catch((e: unknown) => {
        const msg = String((e as Error | undefined)?.message ?? e);
        if (!msg.includes("404")) message.error(msg);
      })
      .finally(() => setLoading(false));
  }, [date]);

  const pickTime = (t: string) => {
    if (!date) return;
    setRankOpen(true);
    getMarketRanking(date.format("YYYY-MM-DD"), t)
      .then(setRanking)
      .catch((e: unknown) => message.error(String((e as Error | undefined)?.message ?? e)));
  };

  const pickStock = (secucode: string) => {
    if (!date) return;
    setStockOpen(true);
    setStockLoading(true);
    setStock(null);
    getStockMinute(date.format("YYYY-MM-DD"), secucode)
      .then(setStock)
      .catch((e: unknown) => message.error(String((e as Error | undefined)?.message ?? e)))
      .finally(() => setStockLoading(false));
  };

  const s = overview?.summary;

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <Card>
        <Space>
          <Text strong>交易日</Text>
          <DatePicker
            value={date}
            onChange={(d) => d && setDate(d)}
            disabledDate={(d) => !dates.includes(d.format("YYYY-MM-DD"))}
            allowClear={false}
          />
        </Space>
      </Card>

      {loading && <Spin />}
      {!loading && !overview && <Empty description="该交易日无分时存档" />}

      {overview && s && (
        <>
          <Card title={<Title level={5} style={{ margin: 0 }}>当日汇总（收盘）</Title>}>
            <Space size="large" wrap>
              <Text>参与 <b>{s.with_pre_close}</b>/{s.total}</Text>
              <Text type="danger">涨停 {s.limit_up}</Text>
              <Text type="danger">上涨 {s.up}</Text>
              <Text type="secondary">平盘 {s.flat}</Text>
              <Text type="success">下跌 {s.down}</Text>
              <Text type="success">跌停 {s.limit_down}</Text>
            </Space>
          </Card>
          <Card title="全市场分时走势（点击曲线某时刻 → 弹出该时刻榜单）">
            <MarketOverviewChart overview={overview} onPickTime={pickTime} />
          </Card>
        </>
      )}

      <MomentRankingModal
        ranking={ranking} open={rankOpen}
        onClose={() => setRankOpen(false)} onPickStock={pickStock}
      />
      <StockMinuteDrawer
        open={stockOpen} data={stock} loading={stockLoading}
        onClose={() => setStockOpen(false)}
      />
    </Space>
  );
}
