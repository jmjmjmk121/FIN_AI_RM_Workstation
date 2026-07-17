import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useApi, fmtFull, titleCase } from "../lib/api.js";
import { ErrorNote, PageHead, Pill, Spinner } from "../components/Bits.jsx";

const GOALS = [
  "retirement",
  "education",
  "protection",
  "liquidity",
  "wealth_transfer",
  "financing",
  "tax",
];

const RISK_TONE = {
  conservative: "green",
  moderate: "green",
  balanced: "blue",
  growth: "amber",
  aggressive: "red",
};

function ProductCard({ item, rank }) {
  return (
    <article className={`row-card${rank === 0 ? " is-top" : ""}`} style={rank === 0 ? { border: "2px solid var(--orange)", background: "#f6eee7" } : undefined}>
      <div className="spread" style={{ alignItems: "flex-start" }}>
        <div>
          <div className="attention-title">
            <h3>{item.name}</h3>
            {rank === 0 ? <Pill tone="amber">Best match</Pill> : null}
            <Pill tone={RISK_TONE[item.risk_level]}>{titleCase(item.risk_level)}</Pill>
            <Pill tone="muted">{titleCase(item.product_type)}</Pill>
          </div>
          <div className="sub-line" style={{ marginTop: 4 }}>{item.description}</div>
        </div>
        <div style={{ textAlign: "right", flex: "none" }}>
          <div className="muted-label">Fit</div>
          <div style={{ fontSize: 22, fontWeight: 900, color: "var(--navy)" }}>{Math.round(item.score)}</div>
        </div>
      </div>

      <div className="metric-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))", margin: "14px 0 0", gap: 10 }}>
        <div>
          <div className="muted-label">Minimum</div>
          <div style={{ fontWeight: 800, color: "var(--navy)" }}>{fmtFull(item.min_investment)} THB</div>
        </div>
        <div>
          <div className="muted-label">Indicative</div>
          <div style={{ fontWeight: 800, color: item.indicative_return_pct < 0 ? "var(--red)" : "var(--green)" }}>
            {item.indicative_return_pct > 0 ? "+" : ""}
            {item.indicative_return_pct}% p.a.
          </div>
        </div>
        <div>
          <div className="muted-label">Horizon</div>
          <div style={{ fontWeight: 800, color: "var(--navy)" }}>{item.horizon_years}y</div>
        </div>
        <div>
          <div className="muted-label">Liquidity</div>
          <div style={{ fontWeight: 800, color: "var(--navy)" }}>
            {item.liquidity_days === 0 ? "n/a" : `T+${item.liquidity_days}`}
          </div>
        </div>
      </div>

      {item.rationale.length > 0 ? (
        <ul style={{ margin: "14px 0 0", paddingLeft: 18, color: "#3f495e" }}>
          {item.rationale.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      ) : null}

      {item.cautions.length > 0 ? (
        <div className="callout callout-guard" style={{ marginTop: 12 }}>
          {item.cautions.map((line) => (
            <div key={line}>· {line}</div>
          ))}
        </div>
      ) : null}
    </article>
  );
}

export default function RecommendationPage() {
  const [params, setParams] = useSearchParams();
  const clientId = params.get("client") || "";
  const [goals, setGoals] = useState([]);
  const [horizon, setHorizon] = useState("");

  const { data: clientList, error: clientError, loading: clientLoading } = useApi("/api/clients");

  const query = useMemo(() => {
    if (!clientId) return null;
    const parts = [`client_id=${encodeURIComponent(clientId)}`];
    goals.forEach((g) => parts.push(`goals=${g}`));
    if (horizon) parts.push(`horizon_years=${horizon}`);
    return `/api/recommendations?${parts.join("&")}`;
  }, [clientId, goals, horizon]);

  const { data, error, loading } = useApi(query ?? "/api/products");

  if (clientLoading) return <Spinner />;
  if (clientError) return <ErrorNote message={clientError} />;

  const toggleGoal = (goal) =>
    setGoals((current) =>
      current.includes(goal) ? current.filter((g) => g !== goal) : [...current, goal]
    );

  const selected = clientList.clients.find((c) => c.client_id === clientId);
  const result = query && !loading && !error ? data : null;

  return (
    <div className="page-enter">
      <PageHead
        eyebrow="Module 2 · Product Recommendation"
        title="Match products to the need"
        lede="Pick a client and the goals you want to address. Suitability, permission, mandate and KYC gates run before anything is ranked — a gated product is never recommended, and you can see exactly why it was ruled out."
      />

      <div className="two-col">
        <div className="card stack" style={{ gap: 16 }}>
          <div className="field">
            <label className="muted-label" htmlFor="client">Client</label>
            <select
              id="client"
              value={clientId}
              onChange={(event) => {
                const next = new URLSearchParams(params);
                if (event.target.value) next.set("client", event.target.value);
                else next.delete("client");
                setParams(next);
              }}
            >
              <option value="">Select a client…</option>
              {clientList.clients.map((client) => (
                <option key={client.client_id} value={client.client_id}>
                  {client.name} · {client.segment}
                </option>
              ))}
            </select>
          </div>

          <div className="field">
            <span className="muted-label">Goals to address</span>
            <div className="chip-row" style={{ marginBottom: 0 }}>
              {GOALS.map((goal) => (
                <button
                  key={goal}
                  className={`chip${goals.includes(goal) ? " is-active" : ""}`}
                  onClick={() => toggleGoal(goal)}
                >
                  {titleCase(goal)}
                </button>
              ))}
            </div>
            {goals.length === 0 ? (
              <div className="sub-line">Leave empty to use the client's confirmed goals.</div>
            ) : null}
          </div>

          <div className="field">
            <label className="muted-label" htmlFor="horizon">Horizon (years)</label>
            <input
              id="horizon"
              type="number"
              min="0"
              max="40"
              placeholder="Any"
              value={horizon}
              onChange={(event) => setHorizon(event.target.value)}
            />
          </div>

          {selected ? (
            <div className="quote-block" style={{ padding: 14 }}>
              <div className="muted-label">Client context</div>
              <div className="stack" style={{ gap: 4, marginTop: 8 }}>
                <div className="spread">
                  <span className="sub-line">Risk profile</span>
                  <Pill tone={RISK_TONE[selected.risk_profile]}>{titleCase(selected.risk_profile)}</Pill>
                </div>
                <div className="spread">
                  <span className="sub-line">Mandate</span>
                  <strong>{titleCase(selected.mandate)}</strong>
                </div>
                <div className="spread">
                  <span className="sub-line">Investable cash</span>
                  <strong>{fmtFull(selected.investable_cash)} THB</strong>
                </div>
                <div className="spread">
                  <span className="sub-line">KYC</span>
                  <strong>{titleCase(selected.kyc_status)}</strong>
                </div>
              </div>
            </div>
          ) : null}
        </div>

        <div>
          {!clientId ? (
            <div className="card">
              <div className="empty">Select a client to see recommendations.</div>
            </div>
          ) : loading ? (
            <Spinner />
          ) : error ? (
            <ErrorNote message={error} />
          ) : result?.blocked ? (
            <div className="card">
              <div className="callout callout-error">
                <strong>Advice is blocked for this client.</strong>
                <div style={{ fontWeight: 400, marginTop: 6 }}>{result.block_reason}</div>
              </div>
              <p className="sub-line" style={{ marginTop: 14 }}>
                All {result.excluded.length} products in the catalogue are withheld. This gate is not
                overridable — clear it first, then return here.
              </p>
            </div>
          ) : result ? (
            <>
              <div className="spread" style={{ marginBottom: 14 }}>
                <h2>
                  {result.recommended.length} product{result.recommended.length === 1 ? "" : "s"} for{" "}
                  {result.client_name}
                </h2>
                <span className="sub-line">
                  {result.goals.length > 0
                    ? result.goals.map(titleCase).join(" · ")
                    : "No goals selected"}
                </span>
              </div>

              {result.recommended.length === 0 ? (
                <div className="card">
                  <div className="empty">
                    No product passes the gates for the selected goals.
                  </div>
                </div>
              ) : (
                <div className="attention-list">
                  {result.recommended.map((item, index) => (
                    <ProductCard key={item.product_id} item={item} rank={index} />
                  ))}
                </div>
              )}

              {result.excluded.length > 0 ? (
                <details className="suppressed" style={{ marginTop: 18 }}>
                  <summary>{result.excluded.length} product(s) ruled out — see why</summary>
                  <div className="table-wrap" style={{ marginTop: 10 }}>
                    <table>
                      <thead>
                        <tr>
                          <th>Product</th>
                          <th>Risk</th>
                          <th>Reason ruled out</th>
                        </tr>
                      </thead>
                      <tbody>
                        {result.excluded.map((item) => (
                          <tr key={item.product_id}>
                            <td className="client-name">{item.name}</td>
                            <td>
                              <Pill tone={RISK_TONE[item.risk_level]}>{titleCase(item.risk_level)}</Pill>
                            </td>
                            <td>
                              {item.reasons.map((reason) => (
                                <div key={reason}>{reason}</div>
                              ))}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </details>
              ) : null}
            </>
          ) : null}
        </div>
      </div>
    </div>
  );
}
