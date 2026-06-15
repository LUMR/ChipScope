import React from "react";
import ReactDOM from "react-dom/client";
import { ConfigProvider, theme } from "antd";
import zhCN from "antd/locale/zh_CN";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { RealtimeProvider } from "./hooks/useRealtimeQuotes";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ConfigProvider
      locale={zhCN}
      theme={{
        token: {
          colorPrimary: "#5b6cff",
          colorBgLayout: "#f6f7f9",
          borderRadius: 8,
          fontFamily:
            "system-ui, 'Segoe UI', Roboto, sans-serif",
        },
        components: {
          Layout: { headerBg: "#ffffff", siderBg: "#ffffff" },
          Menu: { itemSelectedBg: "#eef2ff", itemSelectedColor: "#5b6cff" },
          Table: { headerBg: "#fafafa" },
        },
        algorithm: theme.defaultAlgorithm,
      }}
    >
      <BrowserRouter>
        <RealtimeProvider>
          <App />
        </RealtimeProvider>
      </BrowserRouter>
    </ConfigProvider>
  </React.StrictMode>
);
