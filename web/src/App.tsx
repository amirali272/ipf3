import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import Layout from "./components/Layout";
import { Spinner } from "./components/ui";
import { useAuth } from "./lib/auth";
import Account from "./pages/Account";
import Alerts from "./pages/Alerts";
import Analytics from "./pages/Analytics";
import Audit from "./pages/Audit";
import Dashboard from "./pages/Dashboard";
import JobDetail from "./pages/JobDetail";
import Login from "./pages/Login";
import Schedules from "./pages/Schedules";
import ServerDetail from "./pages/ServerDetail";
import Servers from "./pages/Servers";
import Tests from "./pages/Tests";
import UsersPage from "./pages/Users";
import Usage from "./pages/Usage";
import Subscription from "./pages/Subscription";
import VpnInbounds from "./pages/vpn/Inbounds";
import VpnOutbounds from "./pages/vpn/Outbounds";
import VpnWireguard from "./pages/vpn/Wireguard";
import VpnOverviewPage from "./pages/vpn/Overview";
import VpnUsers from "./pages/vpn/Users";

export default function App() {
  const { user, loading, can } = useAuth();
  const location = useLocation();
  if (location.pathname.startsWith("/s/")) {
    return (
      <Routes>
        <Route path="/s/:token" element={<Subscription />} />
      </Routes>
    );
  }
  if (loading) return <Spinner label="Connecting…" />;
  if (!user) return <Login />;
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<VpnOverviewPage />} />
        <Route path="vpn/users" element={<VpnUsers />} />
        <Route path="vpn/inbounds" element={<VpnInbounds />} />
        <Route path="vpn/outbounds" element={<VpnOutbounds />} />
        <Route path="vpn/wireguard" element={<VpnWireguard />} />
        <Route path="monitoring" element={<Dashboard />} />
        <Route path="servers" element={<Servers />} />
        <Route path="servers/:id" element={<ServerDetail />} />
        <Route path="usage" element={<Usage />} />
        <Route path="tests" element={<Tests />} />
        <Route path="jobs/:id" element={<JobDetail />} />
        <Route path="schedules" element={<Schedules />} />
        <Route path="analytics" element={<Analytics />} />
        <Route path="alerts" element={<Alerts />} />
        <Route path="account" element={<Account />} />
        {can("admin") && <Route path="users" element={<UsersPage />} />}
        {can("admin") && <Route path="audit" element={<Audit />} />}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
