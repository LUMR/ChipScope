import { Navigate, Route, Routes } from "react-router-dom";
import AppLayout from "./components/AppLayout";
import StockDetail from "./pages/StockDetail";
import WatchlistPage from "./pages/WatchlistPage";

export default function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route path="/" element={<Navigate to="/stock/600519.SH" replace />} />
        <Route path="/stock/:secucode" element={<StockDetail />} />
        <Route path="/watchlist" element={<WatchlistPage />} />
      </Route>
    </Routes>
  );
}
