import { Button, Card, DatePicker, message, Progress, Space, Tag, Typography } from "antd";
import dayjs from "dayjs";
import { useEffect, useState } from "react";
import type { ArchiveStatus } from "../api/archive";
import {
  getArchiveStatus,
  triggerArchive,
} from "../api/archive";

const { Text } = Typography;

export default function ArchivePage() {
  const [status, setStatus] = useState<ArchiveStatus | null>(null);
  const [date, setDate] = useState<dayjs.Dayjs | null>(null);
  const [loading, setLoading] = useState(false);

  // 首次加载 + 运行中轮询
  useEffect(() => {
    let timer: ReturnType<typeof setInterval> | undefined;
    getArchiveStatus().then(setStatus);
    timer = setInterval(async () => {
      try {
        setStatus(await getArchiveStatus());
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

  const running = status?.state === "running";
  const pct =
    status && status.total > 0
      ? Math.round(((status.done + status.failed) / status.total) * 100)
      : 0;

  return (
    <Card title="分时行情存档" style={{ maxWidth: 720 }}>
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
  );
}
