import { useState } from "react";
import { Link } from "react-router-dom";
import { useApi, fmtFull, fmtDate, titleCase } from "../lib/api.js";
import { ACTIVITY_TONE, Empty, ErrorNote, Metric, PageHead, Pill, Spinner } from "../components/Bits.jsx";

const FILTERS = [
  { key: "", label: "All clients" },
  { key: "active", label: "Active" },
  { key: "cooling", label: "Cooling" },
  { key: "dormant", label: "Dormant" },
  { key: "inactive", label: "Inactive" },
];

export default function ActivityPage() {
  const [status, setStatus] = useState("");
  const { data, error, loading } = useApi(`/api/activity${status ? `?status=${status}` : ""}`);
  const { data: all } = useApi("/api/activity");

  if (loading) return <Spinner />;
  if (error) return <ErrorNote message={error} />;

  const summary = all?.summary ?? data.summary;
  const byStatus = summary.by_status;

  return (
    <div className="page-enter">
      <PageHead
        eyebrow="Module 3 · Active Clients"
        title="Who has gone quiet"
        lede="Activity is measured from the last client-initiated event — a deposit, withdrawal, or trade. Your own outbound calls do not count, so a client you have been chasing without response still shows as quiet."
      />

      <div className="metric-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))" }}>
        <Metric label="At risk" value={summary.at_risk} sub="dormant or inactive" tone="inverted" />
        <Metric label="Active" value={byStatus.active} sub="< 6 months" />
        <Metric label="Cooling" value={byStatus.cooling} sub="6–12 months" />
        <Metric label="Dormant" value={byStatus.dormant} sub="12–24 months" />
        <Metric label="Inactive" value={byStatus.inactive} sub="24+ months" />
        <Metric
          label="Idle cash at risk"
          value={`${fmtFull(Math.round(summary.idle_cash_at_risk / 1_000_000))}M`}
          sub="THB above reserve, quiet clients"
        />
      </div>

      <div className="chip-row">
        {FILTERS.map((filter) => (
          <button
            key={filter.key}
            className={`chip${status === filter.key ? " is-active" : ""}`}
            onClick={() => setStatus(filter.key)}
          >
            {filter.label}
          </button>
        ))}
      </div>

      {data.rows.length === 0 ? (
        <Empty>No clients in this status.</Empty>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Client</th>
                <th>Status</th>
                <th className="num">Quiet for</th>
                <th>Last activity</th>
                <th>Deposit</th>
                <th>Withdrawal</th>
                <th>Trade</th>
                <th className="num">Idle cash</th>
                <th>Why call now</th>
              </tr>
            </thead>
            <tbody>
              {data.rows.map((row) => (
                <tr key={row.client_id}>
                  <td>
                    <div className="client-name">{row.client_name}</div>
                    <div className="sub-line">
                      {row.client_id} · {row.segment}
                    </div>
                  </td>
                  <td>
                    <Pill tone={ACTIVITY_TONE[row.status]}>{titleCase(row.status)}</Pill>
                  </td>
                  <td className="num">
                    {row.months_since_activity === null ? "—" : `${row.months_since_activity} mo`}
                  </td>
                  <td>
                    <div>{fmtDate(row.last_activity_on)}</div>
                    <div className="sub-line">{titleCase(row.last_activity_kind) || "—"}</div>
                  </td>
                  <td className="sub-line">{fmtDate(row.last_deposit_on)}</td>
                  <td className="sub-line">{fmtDate(row.last_withdrawal_on)}</td>
                  <td className="sub-line">{fmtDate(row.last_trade_on)}</td>
                  <td className="num">
                    <strong>{fmtFull(row.idle_cash)}</strong>
                    {row.matured_value > 0 ? (
                      <div className="sub-line" style={{ color: "var(--amber)" }}>
                        +{fmtFull(row.matured_value)} matured
                      </div>
                    ) : null}
                  </td>
                  <td>
                    {row.reengagement_reason ? (
                      <Link className="soft-button" to={`/recommend?client=${row.client_id}`}>
                        {row.reengagement_reason}
                      </Link>
                    ) : (
                      <span className="sub-line">—</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
