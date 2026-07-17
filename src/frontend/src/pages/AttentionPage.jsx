import { useState } from "react";
import { Link } from "react-router-dom";
import { useApi, fmtFull, titleCase } from "../lib/api.js";
import { Empty, ErrorNote, Metric, PageHead, Pill, SeverityDot, Spinner } from "../components/Bits.jsx";

const LANES = [
  { key: "", label: "All lanes" },
  { key: "care", label: "Care lane" },
  { key: "growth", label: "Growth lane" },
];

function AttentionCard({ item }) {
  const isCare = item.lane === "care";

  return (
    <article className={`row-card lane-${item.lane}`}>
      <div className="attention-head">
        <div>
          <div className="attention-title">
            <h3>{item.client_name}</h3>
            <Pill tone={isCare ? "care" : "growth"}>{isCare ? "Care lane" : "Growth lane"}</Pill>
            <Pill tone="muted">{item.segment}</Pill>
            {!item.contact_allowed ? <Pill tone="red">Contact blocked</Pill> : null}
          </div>
          <div className="sub-line" style={{ marginTop: 4 }}>
            {item.client_id} · {item.headline}
          </div>
        </div>
        <div style={{ textAlign: "right", flex: "none" }}>
          <div className="muted-label">Priority</div>
          <div style={{ fontSize: 22, fontWeight: 900, color: "var(--navy)" }}>
            {Math.round(item.score)}
          </div>
        </div>
      </div>

      {!item.contact_allowed ? (
        <div className="callout callout-error" style={{ marginTop: 12 }}>
          {item.contact_block_reason}. Resolve the permission before contacting.
        </div>
      ) : null}

      <div className="attention-body">
        {item.signals.map((signal) => (
          <div className="signal" key={signal.code + signal.title}>
            <SeverityDot severity={signal.severity} />
            <div className="signal-text">
              <strong>{signal.title}</strong>
              <span>{signal.detail}</span>
            </div>
          </div>
        ))}
      </div>

      <div className="nba">Next best action — {item.next_best_action}</div>

      {item.suppressed_growth.length > 0 ? (
        <details className="suppressed">
          <summary>
            {item.suppressed_growth.length} growth opportunit
            {item.suppressed_growth.length === 1 ? "y" : "ies"} held back
          </summary>
          <div className="callout callout-guard">
            {item.lane_rationale}
            <ul style={{ margin: "8px 0 0", paddingLeft: 18, fontWeight: 400 }}>
              {item.suppressed_growth.map((signal) => (
                <li key={signal.code + signal.title}>
                  <strong>{signal.title}</strong> — {signal.detail}
                </li>
              ))}
            </ul>
          </div>
        </details>
      ) : null}

      <div style={{ marginTop: 14 }}>
        <Link className="soft-button" to={`/recommend?client=${item.client_id}`}>
          Open in product recommendation →
        </Link>
      </div>
    </article>
  );
}

export default function AttentionPage() {
  const [lane, setLane] = useState("");
  const { data, error, loading } = useApi(`/api/attention${lane ? `?lane=${lane}` : ""}`);

  if (loading) return <Spinner />;
  if (error) return <ErrorNote message={error} />;

  const { summary, items } = data;

  return (
    <div className="page-enter">
      <PageHead
        eyebrow="Module 1 · Attention & Channel"
        title="Who needs you today"
        lede="Ranked by what the client needs, not by what they are worth. A client with an open care gate always outranks an opportunity, and their growth signals are held back until the gate clears."
      />

      <div className="metric-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))" }}>
        <Metric label="Need attention" value={summary.total} sub={`of your book today`} tone="inverted" />
        <Metric label="Care lane" value={summary.care} sub="client-benefit gates open" tone="care" />
        <Metric label="Growth lane" value={summary.growth} sub="confirmed or evidenced need" tone="growth" />
        <Metric
          label="Growth held back"
          value={summary.suppressed_growth_clients}
          sub="blocked by a care gate"
        />
        <Metric label="Contact blocked" value={summary.blocked} sub="permission or DND" />
      </div>

      <div className="chip-row">
        {LANES.map((option) => (
          <button
            key={option.key}
            className={`chip${lane === option.key ? " is-active" : ""}`}
            onClick={() => setLane(option.key)}
          >
            {option.label}
          </button>
        ))}
      </div>

      {items.length === 0 ? (
        <Empty>Nothing in this lane today.</Empty>
      ) : (
        <div className="attention-list">
          {items.map((item) => (
            <AttentionCard key={item.client_id} item={item} />
          ))}
        </div>
      )}
    </div>
  );
}
