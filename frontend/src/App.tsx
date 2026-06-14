import { Routes, Route, Navigate } from "react-router-dom";
import StockDetail from "./pages/StockDetail";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/stock/600519.SH" replace />} />
      <Route path="/stock/:secucode" element={<StockDetail />} />
    </Routes>
  );
}
