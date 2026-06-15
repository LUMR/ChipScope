import { Layout } from "antd";
import { Outlet } from "react-router-dom";
import SiderWatchlist from "./SiderWatchlist";
import TopNav from "./TopNav";

const { Header, Sider, Content } = Layout;

export default function AppLayout() {
  return (
    <Layout style={{ minHeight: "100vh" }}>
      <Header style={{ background: "#fff", padding: "0 24px", height: 56 }}>
        <TopNav />
      </Header>
      <Layout>
        <Sider width={220} theme="light" style={{ borderRight: "1px solid #f0f0f0" }}>
          <SiderWatchlist />
        </Sider>
        <Content style={{ padding: 16, background: "#f6f7f9" }}>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  );
}
