import { Card, DatePicker, Empty, message, Space, Spin, Typography } from "antd";
import dayjs, { Dayjs } from "dayjs";
import { useEffect, useState } from "react";
import { getMarketDates, getMarketOverview, type Overview } from "../api/market";
import MarketOverviewChart from "../components/MarketOverviewChart";

const { Text, Title } = Typography;

export default function MarketMinutePage() {
  const [dates, setDates] = useState<string[]>([]);
  const [date, setDate] = useState<Dayjs | null>(null);
  const [overview, setOverview] = useState<Overview | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    getMarketDates().then((ds) => {
      setDates(ds);
      if (ds.length) setDate(dayjs(ds[0]));
    }).catch(() => message.error("加载可用交易日失败"));
  }, []);

  useEffect(() => {
    if (!date) return;
    setLoading(true);
    getMarketOverview(date.format("YYYY-MM-DD"))
      .then(setOverview)
      .catch((e: any) => {
        const msg = String(e?.message || e);
        if (msg.includes("404")) {
          setOverview(null);
        } else {
          message.error(msg);
        }
      })
      .finally(() => setLoading(false));
  }, [date]);

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
          <Card title="全市场分时走势">
            <MarketOverviewChart overview={overview} onPickTime={() => {}} />
          </Card>
        </>
      )}
    </Space>
  );
}
