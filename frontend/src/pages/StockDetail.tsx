import { useEffect, useState } from "react";
import { Alert, Spin } from "antd";
import { useParams } from "react-router-dom";
import ChipFlame from "../components/ChipFlame";
import DateSlider from "../components/DateSlider";
import KLineChart from "../components/KLineChart";
import MetricPanel from "../components/MetricPanel";
import { getChips } from "../api/stocks";
import { useStockData } from "../hooks/useStockData";
import type { ChipDistribution } from "../types/domain";

export default function StockDetail() {
  const { secucode = "600519.SH" } = useParams();
  const { kline, pattern, loading, error } = useStockData(secucode);
  const [dateIdx, setDateIdx] = useState(0);
  const [chip, setChip] = useState<ChipDistribution | undefined>();

  const dates = kline.map((k) => k.ts.slice(0, 10));

  useEffect(() => {
    setDateIdx(Math.max(0, dates.length - 1));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [secucode, dates.length]);

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

  if (loading) return <Spin />;
  if (error) return <Alert type="error" message={error} />;

  return (
    <>
      <KLineChart bars={kline} />
      <DateSlider dates={dates} value={dateIdx} onChange={setDateIdx} />
      <ChipFlame chip={chip} />
      <div style={{ marginTop: 16 }}>
        <MetricPanel chip={chip} pattern={pattern} />
      </div>
    </>
  );
}
