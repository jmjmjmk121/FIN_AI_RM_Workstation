import { useState } from "react";
import { useApi, fmtDate, titleCase } from "../lib/api.js";
import { Empty, ErrorNote, KYC_TONE, Metric, PageHead, Pill, Spinner } from "../components/Bits.jsx";

const FILTERS = [
  { key: "", label: "All clients" },
  { key: "overdue", label: "Overdue" },
  { key: "missing", label: "Documents missing" },
  { key: "due_soon", label: "Due soon" },
  { key: "valid", label: "Valid" },
];

const AML_TONE = { low: "green", medium: "amber", high: "red" };

function ExpiryCell({ row }) {
  if (row.days_to_expiry === null) return <span className="sub-line">No expiry on file</span>;
  const overdue = row.days_to_expiry < 0;
  return (
    <div>
      <div style={{ fontWeight: 800, color: overdue ? "var(--red)" : "var(--navy)" }}>
        {fmtDate(row.expires_on)}
      </div>
      <div className="sub-line" style={{ color: overdue ? "var(--red)" : undefined }}>
        {overdue ? `${Math.abs(row.days_to_expiry)} days overdue` : `in ${row.days_to_expiry} days`}
      </div>
    </div>
  );
}

export default function KycPage() {
  const [status, setStatus] = useState("");
  const { data, error, loading } = useApi(`/api/kyc${status ? `?status=${status}` : ""}`);
  const { data: all } = useApi("/api/kyc");

  if (loading) return <Spinner />;
  if (error) return <ErrorNote message={error} />;

  const summary = all?.summary ?? data.summary;
  const byStatus = summary.by_status;

  return (
    <div className="page-enter">
      <PageHead
        eyebrow="Module 4 · KYC & Compliance"
        title="KYC status across your book"
        lede="Status is derived from the record's own dates on every load, never read from a stored label — a stale overnight batch cannot make an expired KYC look valid. Anything that blocks advice is listed first."
      />

      <div className="metric-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))" }}>
        <Metric label="Advice blocked" value={summary.advice_blocked} sub="cannot be advised today" tone="inverted" />
        <Metric label="Overdue" value={byStatus.overdue} sub="KYC lapsed" />
        <Metric label="Documents missing" value={byStatus.missing} sub="outstanding items" />
        <Metric label="Due in 60 days" value={summary.renewals_due_60d} sub="renewal window open" />
        <Metric label="Suitability overdue" value={summary.suitability_overdue} sub="re-assessment needed" />
        <Metric label="High AML risk" value={summary.high_aml_risk} sub="enhanced due diligence" />
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
                <th>KYC status</th>
                <th>Expires</th>
                <th>Last review</th>
                <th>AML risk</th>
                <th>Outstanding</th>
                <th>Action</th>
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
                    <Pill tone={KYC_TONE[row.status]}>{titleCase(row.status)}</Pill>
                    {row.advice_blocked ? (
                      <div className="sub-line" style={{ color: "var(--red)", marginTop: 4 }}>
                        Advice blocked
                      </div>
                    ) : null}
                  </td>
                  <td><ExpiryCell row={row} /></td>
                  <td className="sub-line">{fmtDate(row.last_review_on)}</td>
                  <td>
                    <Pill tone={AML_TONE[row.aml_risk_rating] ?? "muted"}>
                      {titleCase(row.aml_risk_rating)}
                    </Pill>
                  </td>
                  <td>
                    {row.missing_documents.length > 0 ? (
                      row.missing_documents.map((doc) => (
                        <div key={doc} className="sub-line" style={{ color: "var(--red)" }}>
                          · {doc}
                        </div>
                      ))
                    ) : row.suitability_overdue ? (
                      <div className="sub-line" style={{ color: "var(--amber)" }}>
                        Suitability lapsed {fmtDate(row.suitability_expires_on)}
                      </div>
                    ) : (
                      <span className="sub-line">—</span>
                    )}
                  </td>
                  <td style={{ maxWidth: 260 }}>{row.action}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
