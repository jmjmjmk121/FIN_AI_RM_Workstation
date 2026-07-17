export function Spinner() {
  return <div className="spinner" aria-label="Loading" />;
}

export function ErrorNote({ message }) {
  return (
    <div className="callout callout-error">
      {message}
      <div style={{ fontWeight: 400, marginTop: 6 }}>
        Is the API running? Start it with <code>npm run api</code>.
      </div>
    </div>
  );
}

export function Empty({ children }) {
  return <div className="empty">{children}</div>;
}

export function Metric({ label, value, sub, tone }) {
  return (
    <div className={`metric${tone ? ` ${tone}` : ""}`}>
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {sub ? <div className="sub">{sub}</div> : null}
    </div>
  );
}

export function Pill({ tone = "muted", children }) {
  return <span className={`pill pill-${tone}`}>{children}</span>;
}

/** Severity 1–5 mapped onto the semantic pairs. */
export function SeverityDot({ severity }) {
  const color = severity >= 5 ? "var(--red)" : severity >= 4 ? "var(--amber)" : "var(--blue)";
  return <span className="sev-dot" style={{ background: color, marginTop: 6 }} />;
}

export const KYC_TONE = { valid: "green", due_soon: "amber", overdue: "red", missing: "red" };
export const ACTIVITY_TONE = { active: "green", cooling: "amber", dormant: "red", inactive: "red" };

export function PageHead({ eyebrow, title, lede, children }) {
  return (
    <header className="page-head">
      <div className="spread">
        <div>
          <p className="eyebrow">{eyebrow}</p>
          <h1>{title}</h1>
        </div>
        {children}
      </div>
      {lede ? <p className="lede">{lede}</p> : null}
    </header>
  );
}
