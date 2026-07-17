import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { useApi, fmtDate } from "./lib/api.js";
import AttentionPage from "./pages/AttentionPage.jsx";
import RecommendationPage from "./pages/RecommendationPage.jsx";
import ActivityPage from "./pages/ActivityPage.jsx";
import KycPage from "./pages/KycPage.jsx";

function Nav() {
  const { data: attention } = useApi("/api/attention?limit=1");
  const { data: kyc } = useApi("/api/kyc");
  const { data: activity } = useApi("/api/activity");

  const careCount = attention?.summary?.care;
  const kycCount = kyc?.summary?.by_status
    ? kyc.summary.by_status.overdue + kyc.summary.by_status.missing + kyc.summary.by_status.due_soon
    : undefined;
  const atRisk = activity?.summary?.at_risk;

  const tabs = [
    { to: "/attention", label: "Today's attention", count: careCount },
    { to: "/recommend", label: "Product recommendation" },
    { to: "/activity", label: "Active clients", count: atRisk },
    { to: "/kyc", label: "KYC", count: kycCount },
  ];

  return (
    <nav className="nav">
      {tabs.map((tab) => (
        <NavLink
          key={tab.to}
          to={tab.to}
          className={({ isActive }) => `nav-item${isActive ? " is-active" : ""}`}
        >
          {tab.label}
          {tab.count !== undefined ? <span className="nav-count">{tab.count}</span> : null}
        </NavLink>
      ))}
    </nav>
  );
}

function Topbar() {
  const { data } = useApi("/api/health");
  const source = data?.market?.source;
  const degraded = data?.market?.degraded_reason;
  const closeDate = data?.market?.as_of;

  // A live feed lagging the business date by a day is just how EOD works — say
  // the close date rather than raising an alarm. Only a real fallback is a warning.
  const label = source === "live" ? "Live" : "Fixture";
  const detail = degraded
    ? "degraded"
    : closeDate
    ? `close ${fmtDate(closeDate)}`
    : null;

  return (
    <header className="topbar">
      <div className="topbar-brand">
        <strong>RM AI Workstation</strong>
        <span>Relationship Management</span>
      </div>
      <div className="topbar-meta">
        <div>
          <span className="label">Market data</span>
          <span
            className="value"
            title={degraded || (closeDate ? `Latest published close: ${closeDate}` : undefined)}
            style={degraded ? { color: "#ff9a50" } : undefined}
          >
            SETSMART · {label}
            {detail ? ` · ${detail}` : ""}
          </span>
        </div>
        <div>
          <span className="label">RM</span>
          <span className="value">{data?.config?.rm_id ?? "—"}</span>
        </div>
        <div>
          <span className="label">As of</span>
          <span className="value">{data?.as_of ? fmtDate(data.as_of) : "—"}</span>
        </div>
      </div>
    </header>
  );
}

export default function App() {
  return (
    <>
      <Topbar />
      <Nav />
      <main className="app-shell">
        <Routes>
          <Route path="/" element={<Navigate to="/attention" replace />} />
          <Route path="/attention" element={<AttentionPage />} />
          <Route path="/recommend" element={<RecommendationPage />} />
          <Route path="/activity" element={<ActivityPage />} />
          <Route path="/kyc" element={<KycPage />} />
        </Routes>
      </main>
    </>
  );
}
