import { Button, Card, DatePicker, message, Progress, Select, Space, Tag, Typography } from "antd";
import dayjs from "dayjs";
import { useEffect, useState } from "react";
import type { ArchiveStatus, BackfillStatus } from "../api/archive";
import {
  getArchiveStatus,
  getChipBackfillStatus,
  getDailyKlineArchiveStatus,
  getMetricsArchiveStatus,
  triggerArchive,
  triggerChipBackfill,
  triggerDailyKlineArchive,
  triggerMetricsArchive,
} from "../api/archive";

const { Text } = Typography;

export default function ArchivePage() {
  const [status, setStatus] = useState<ArchiveStatus | null>(null);
  const [date, setDate] = useState<dayjs.Dayjs | null>(null);
  const [loading, setLoading] = useState(false);

  const [backfillStatus, setBackfillStatus] = useState<BackfillStatus | null>(null);
  const [daysWindow, setDaysWindow] = useState<string>("365");
  const [backfillLoading, setBackfillLoading] = useState(false);

  const [klineStatus, setKlineStatus] = useState<ArchiveStatus | null>(null);
  const [klineCount, setKlineCount] = useState<number>(250);
  const [klineLoading, setKlineLoading] = useState(false);

  const [metricStatus, setMetricStatus] = useState<ArchiveStatus | null>(null);
  const [metricDays, setMetricDays] = useState<string>("60");
  const [metricLoading, setMetricLoading] = useState(false);

  // 分时存档：首次加载 + 运行中轮询
  useEffect(() => {
    getArchiveStatus().then(setStatus);
    const timer = setInterval(async () => {
      try {
        setStatus(await getArchiveStatus());
      } catch {
        /* ignore */
      }
    }, 2000);
    return () => clearInterval(timer);
  }, []);

  // 筹码补全：首次加载 + 运行中轮询
  useEffect(() => {
    getChipBackfillStatus().then(setBackfillStatus);
    const timer = setInterval(async () => {
      try {
        setBackfillStatus(await getChipBackfillStatus());
      } catch {
        /* ignore */
      }
    }, 2000);
    return () => clearInterval(timer);
  }, []);

  // 日K回档：首次加载 + 运行中轮询
  useEffect(() => {
    getDailyKlineArchiveStatus().then(setKlineStatus);
    const timer = setInterval(async () => {
      try {
        setKlineStatus(await getDailyKlineArchiveStatus());
      } catch {
        /* ignore */
      }
    }, 2000);
    return () => clearInterval(timer);
  }, []);

  // 指标物化：首次加载 + 运行中轮询
  useEffect(() => {
    getMetricsArchiveStatus().then(setMetricStatus);
    const timer = setInterval(async () => {
      try {
        setMetricStatus(await getMetricsArchiveStatus());
      } catch {
        /* ignore */
      }
    }, 2000);
    return () => clearInterval(timer);
  }, []);

  const trigger = async () => {
    setLoading(true);
    try {
      const dateStr = date ? date.format("YYYY-MM-DD") : undefined;
      await triggerArchive(dateStr);
      message.success("已开始存档，请关注进度");
    } catch (e: any) {
      const msg = String(e?.message || e);
      if (msg.includes("409")) {
        message.warning("已有存档任务在运行");
      } else {
        message.error(msg);
      }
    } finally {
      setLoading(false);
    }
  };

  const triggerBackfill = async () => {
    setBackfillLoading(true);
    try {
      await triggerChipBackfill(daysWindow);
      message.success("已开始补全，请关注进度");
    } catch (e: any) {
      const msg = String(e?.message || e);
      if (msg.includes("409")) {
        message.warning("已有补全任务在运行");
      } else {
        message.error(msg);
      }
    } finally {
      setBackfillLoading(false);
    }
  };

  const triggerKline = async () => {
    setKlineLoading(true);
    try {
      await triggerDailyKlineArchive(klineCount);
      message.success("已开始回档，请关注进度");
    } catch (e: any) {
      const msg = String(e?.message || e);
      if (msg.includes("409")) {
        message.warning("已有回档任务在运行");
      } else {
        message.error(msg);
      }
    } finally {
      setKlineLoading(false);
    }
  };

  const triggerMetric = async () => {
    setMetricLoading(true);
    try {
      await triggerMetricsArchive(metricDays);
      message.success("已开始物化，请关注进度");
    } catch (e: unknown) {
      const msg = String((e as Error | undefined)?.message ?? e);
      if (msg.includes("409")) {
        message.warning("已有物化任务在运行");
      } else {
        message.error(msg);
      }
    } finally {
      setMetricLoading(false);
    }
  };

  const running = status?.state === "running";
  const pct =
    status && status.total > 0
      ? Math.round((status.done / status.total) * 100)
      : 0;

  const backfillRunning = backfillStatus?.state === "running";
  const backfillPct =
    backfillStatus && backfillStatus.total > 0
      ? Math.round((backfillStatus.done / backfillStatus.total) * 100)
      : 0;

  const klineRunning = klineStatus?.state === "running";
  const klinePct =
    klineStatus && klineStatus.total > 0
      ? Math.round((klineStatus.done / klineStatus.total) * 100)
      : 0;

  const metricRunning = metricStatus?.state === "running";
  const metricPct =
    metricStatus && metricStatus.total > 0
      ? Math.round((metricStatus.done / metricStatus.total) * 100)
      : 0;

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%", maxWidth: 720 }}>
      <Card title="分时行情存档">
        <Space direction="vertical" size="middle" style={{ width: "100%" }}>
          <div>
            <Text type="secondary">
              把全市场沪深 A 股当天分时数据（每只 ~240 个分钟点）落库。
              默认当天，可选历史日（仅最近若干交易日可补）。
            </Text>
          </div>
          <Space>
            <DatePicker
              value={date}
              onChange={setDate}
              placeholder="留空=当天"
              allowClear
            />
            <Button type="primary" loading={loading} onClick={trigger} disabled={running}>
              {running ? "存档中…" : "开始存档"}
            </Button>
          </Space>
          {status && status.state && (
            <div>
              <Space>
                <Tag color={status.state === "done" ? "green" : status.state === "error" ? "red" : "blue"}>
                  {status.state}
                </Tag>
                <Text>交易日：{status.trade_date ?? "-"}</Text>
              </Space>
              <Progress percent={pct} status={status.state === "error" ? "exception" : running ? "active" : "normal"} />
              <Space size="large">
                <Text>总计 {status.total}</Text>
                <Text type="success">成功 {status.ok}</Text>
                <Text type="danger">失败 {status.failed}</Text>
              </Space>
              {status.error && <Text type="danger">错误：{status.error}</Text>}
            </div>
          )}
        </Space>
      </Card>

      <Card title="自选股筹码补全">
        <Space direction="vertical" size="middle" style={{ width: "100%" }}>
          <div>
            <Text type="secondary">
              对所有自选股重新拉取日K并全量重算筹码分布，补齐因停机/漏采缺失的历史日期。
              一次运行会把每只自选股全部已有日K对应的日期筹码刷新补齐。
            </Text>
          </div>
          <Space>
            <Select
              value={daysWindow}
              onChange={setDaysWindow}
              style={{ width: 140 }}
              options={[
                { value: "120", label: "最近 120 天" },
                { value: "365", label: "最近 365 天" },
                { value: "all", label: "全部（~1000 天）" },
              ]}
            />
            <Button
              type="primary"
              loading={backfillLoading}
              onClick={triggerBackfill}
              disabled={backfillRunning}
            >
              {backfillRunning ? "补全中…" : "开始补全"}
            </Button>
          </Space>
          {backfillStatus && backfillStatus.state && (
            <div>
              <Space>
                <Tag color={backfillStatus.state === "done" ? "green" : backfillStatus.state === "error" ? "red" : "blue"}>
                  {backfillStatus.state}
                </Tag>
                <Text>窗口：{backfillStatus.window ?? "-"}</Text>
              </Space>
              <Progress
                percent={backfillPct}
                status={backfillStatus.state === "error" ? "exception" : backfillRunning ? "active" : "normal"}
              />
              <Space size="large">
                <Text>总计 {backfillStatus.total}</Text>
                <Text type="success">成功 {backfillStatus.ok}</Text>
                <Text type="danger">失败 {backfillStatus.failed}</Text>
              </Space>
              {backfillStatus.error && <Text type="danger">错误：{backfillStatus.error}</Text>}
            </div>
          )}
        </Space>
      </Card>

      <Card title="日K回档">
        <Space direction="vertical" size="middle" style={{ width: "100%" }}>
          <div>
            <Text type="secondary">
              回档全市场日K（默认 250 根，每日 16:10 增量）。覆盖全部沪深 A 股，
              幂等 upsert，可作为选股/指标计算的数据底座。
            </Text>
          </div>
          <Space>
            <Select
              value={String(klineCount)}
              onChange={(v) => setKlineCount(Number(v))}
              style={{ width: 140 }}
              options={[
                { value: "120", label: "最近 120 根" },
                { value: "250", label: "最近 250 根" },
                { value: "500", label: "最近 500 根" },
                { value: "1000", label: "最近 1000 根" },
              ]}
            />
            <Button
              type="primary"
              loading={klineLoading}
              onClick={triggerKline}
              disabled={klineRunning}
            >
              {klineRunning ? "回档中…" : "开始回档"}
            </Button>
          </Space>
          {klineStatus && klineStatus.state && (
            <div>
              <Space>
                <Tag color={klineStatus.state === "done" ? "green" : klineStatus.state === "error" ? "red" : "blue"}>
                  {klineStatus.state}
                </Tag>
                <Text>交易日：{klineStatus.trade_date ?? "-"}</Text>
              </Space>
              <Progress
                percent={klinePct}
                status={klineStatus.state === "error" ? "exception" : klineRunning ? "active" : "normal"}
              />
              <Space size="large">
                <Text>总计 {klineStatus.total}</Text>
                <Text type="success">成功 {klineStatus.ok}</Text>
                <Text type="danger">失败 {klineStatus.failed}</Text>
              </Space>
              {klineStatus.error && <Text type="danger">错误：{klineStatus.error}</Text>}
            </div>
          )}
        </Space>
      </Card>

      <Card title="指标物化">
        <Space direction="vertical" size="middle" style={{ width: "100%" }}>
          <div>
            <Text type="secondary">
              盘后预计算全市场技术指标（MACD/KDJ/WR/RSI 共振）入 stock_metric，每日 16:15 增量。
              选股筛选/副图查此表，秒级响应。首次可选 60/250/all 回填历史。
            </Text>
          </div>
          <Space>
            <Select
              value={metricDays}
              onChange={setMetricDays}
              style={{ width: 140 }}
              options={[
                { value: "60", label: "最近 60 天" },
                { value: "250", label: "最近 250 天" },
                { value: "all", label: "全部（daily_kline 已有）" },
              ]}
            />
            <Button
              type="primary"
              loading={metricLoading}
              onClick={triggerMetric}
              disabled={metricRunning}
            >
              {metricRunning ? "物化中…" : "开始物化"}
            </Button>
          </Space>
          {metricStatus && metricStatus.state && (
            <div>
              <Space>
                <Tag color={metricStatus.state === "done" ? "green" : metricStatus.state === "error" ? "red" : "blue"}>
                  {metricStatus.state}
                </Tag>
                <Text>窗口：{metricStatus.trade_date ?? "-"}</Text>
              </Space>
              <Progress
                percent={metricPct}
                status={metricStatus.state === "error" ? "exception" : metricRunning ? "active" : "normal"}
              />
              <Space size="large">
                <Text>总计 {metricStatus.total}</Text>
                <Text type="success">成功 {metricStatus.ok}</Text>
                <Text type="danger">失败 {metricStatus.failed}</Text>
              </Space>
              {metricStatus.error && <Text type="danger">错误：{metricStatus.error}</Text>}
            </div>
          )}
        </Space>
      </Card>
    </Space>
  );
}
