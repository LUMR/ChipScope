import { Menu } from "antd";
import { useNavigate, useParams } from "react-router-dom";

const DEFAULT_WATCH = [
  { secucode: "600519.SH", name: "贵州茅台" },
  { secucode: "000001.SZ", name: "平安银行" },
  { secucode: "000858.SZ", name: "五粮液" },
  { secucode: "601318.SH", name: "中国平安" },
  { secucode: "002594.SZ", name: "比亚迪" },
];

export default function Watchlist() {
  const nav = useNavigate();
  const { secucode } = useParams();
  return (
    <Menu
      mode="inline"
      selectedKeys={secucode ? [secucode] : []}
      style={{ borderRight: 0 }}
      items={DEFAULT_WATCH.map((w) => ({
        key: w.secucode,
        label: w.name,
        onClick: () => nav(`/stock/${w.secucode}`),
      }))}
    />
  );
}
