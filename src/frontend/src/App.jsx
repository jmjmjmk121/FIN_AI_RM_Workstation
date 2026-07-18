import { NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useApi, fmtDate } from "./lib/api.js";
import ClientsPage from "./pages/ClientsPage.jsx";
import ClientWorkspacePage from "./pages/ClientWorkspacePage.jsx";
import ProductDecisionPage from "./pages/ProductDecisionPage.jsx";
import DashboardPage from "./pages/DashboardPage.jsx";
import KycPage from "./pages/KycPage.jsx";

function Nav() {
  const tabs = [
    { to: "/clients", label: "ลูกค้า" },
    { to: "/products", label: "Product" },
    { to: "/dashboard", label: "Dashboard" },
    { to: "/kyc", label: "KYC" },
  ];
  return (
    <nav className="nav" aria-label="เมนูหลัก">
      {tabs.map((tab) => (
        <NavLink key={tab.to} to={tab.to} className={({ isActive }) => `nav-item${isActive ? " is-active" : ""}`}>
          {tab.label}
        </NavLink>
      ))}
    </nav>
  );
}

function Topbar() {
  const location = useLocation();
  const { data } = useApi("/api/health");
  const { data: book } = useApi("/api/dashboard");
  const clientId = location.pathname.match(/^\/clients\/([^/]+)/)?.[1] || new URLSearchParams(location.search).get("clientId");
  const { data: selected } = useApi(clientId ? `/api/clients/${clientId}` : "/api/health");
  const source = data?.market?.source;
  const degraded = data?.market?.degraded_reason;
  return (
    <header className="topbar">
      <div className="topbar-brand">
        <strong>FIN AI</strong><span>Goal-conditioned RM Workstation</span>
      </div>
      <div className="command-bar" aria-label="ค้นหา">⌕ ค้นหาลูกค้า เป้าหมาย หรือ Product <kbd>⌘ K</kbd></div>
      <div className="topbar-meta">
        {clientId ? <div><span className="label">ลูกค้าที่เลือก</span><span className="value">{selected?.client?.name || clientId}</span></div> : null}
        <div><span className="label">Market data</span><span className="value" style={degraded ? { color: "#ffb17a" } : undefined}>SETSMART · {source === "live" ? "Live" : "Fixture"}</span></div>
        <div><span className="label">RM identity</span><span className="value">{data?.config?.rm_id ?? "—"} · Relationship Manager</span><span className="topbar-sub">{book?.summary?.clients ?? "—"} ลูกค้าใน Book · {book?.summary?.review_today ?? "—"} ทบทวนวันนี้</span><span className="topbar-sub">{book?.summary?.care ?? "—"} Care · แสดง Top {book?.summary?.top_visible ?? "—"}</span></div>
        <div><span className="label">As of</span><span className="value">{data?.as_of ? fmtDate(data.as_of) : "—"}</span></div>
      </div>
    </header>
  );
}

export default function App() {
  return <><Topbar /><Nav /><main className="app-shell"><Routes>
    <Route path="/" element={<Navigate to="/dashboard" replace />} />
    <Route path="/clients" element={<ClientsPage />} />
    <Route path="/clients/:clientId" element={<ClientWorkspacePage />} />
    <Route path="/products" element={<ProductDecisionPage />} />
    <Route path="/dashboard" element={<DashboardPage />} />
    <Route path="/kyc" element={<KycPage />} />
    <Route path="/attention" element={<Navigate to="/dashboard" replace />} />
    <Route path="/recommend" element={<Navigate to="/products" replace />} />
    <Route path="/activity" element={<Navigate to="/dashboard" replace />} />
    <Route path="*" element={<Navigate to="/dashboard" replace />} />
  </Routes></main></>;
}
