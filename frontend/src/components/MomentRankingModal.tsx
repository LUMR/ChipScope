import { Modal, Table, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import type { RankItem, Ranking } from "../api/market";

const { Text } = Typography;

const columns = (onPick: (s: string) => void): ColumnsType<RankItem> => [
  { title: "代码", dataIndex: "secucode", render: (v: string) => <a onClick={() => onPick(v)}>{v}</a> },
  { title: "名称", dataIndex: "name" },
  { title: "现价", dataIndex: "price", align: "right", render: (v: number) => v.toFixed(2) },
  {
    title: "涨幅", dataIndex: "pct", align: "right",
    render: (v: number) => {
      const color = v > 0 ? "#f5222d" : v < 0 ? "#16a34a" : "#9ca3af";
      return <span style={{ color }}>{v >= 0 ? "+" : ""}{v.toFixed(2)}%</span>;
    },
  },
];

export default function MomentRankingModal({
  ranking, open, onClose, onPickStock,
}: {
  ranking: Ranking | null;
  open: boolean;
  onClose: () => void;
  onPickStock: (secucode: string) => void;
}) {
  return (
    <Modal
      title={ranking ? `分时榜单 · ${ranking.time}` : "分时榜单"}
      open={open}
      onCancel={onClose}
      footer={null}
      width={640}
    >
      {ranking && (
        <>
          <Text type="danger">涨幅前 {ranking.gainers.length}</Text>
          <Table
            size="small" pagination={false} rowKey="secucode"
            dataSource={ranking.gainers} columns={columns(onPickStock)}
          />
          <Text type="success" style={{ display: "block", marginTop: 12 }}>
            跌幅前 {ranking.losers.length}
          </Text>
          <Table
            size="small" pagination={false} rowKey="secucode"
            dataSource={ranking.losers} columns={columns(onPickStock)}
          />
        </>
      )}
    </Modal>
  );
}
