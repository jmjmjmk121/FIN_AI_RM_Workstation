import { useEffect, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { WorkspaceProvider } from "../WorkspaceContext.jsx";
import { apiGet, apiSend, useApi, fmtDate, fmtFull, fmtTHB, friendlyCalcId, titleCase } from "../lib/api.js";
import { Empty, ErrorNote, Metric, PageHead, Pill, Spinner, KYC_TONE, ACTIVITY_TONE } from "../components/Bits.jsx";

const SECTIONS = [
  ["overview", "ภาพรวม"], ["goals", "เป้าหมาย"], ["portfolio", "พอร์ตและการจัดสรร"],
  ["quant", "Calculation"], ["activity", "กิจกรรมและ CRM"], ["kyc", "KYC / เอกสาร"],
  ["tasks", "งานและการส่งต่อ"], ["audit", "Audit"],
];

const pct = (v) => v === null || v === undefined ? "—" : `${(v * 100).toFixed(1)}%`;

function Allocation({ holdings }) {
  const colors = ["#18243f", "#ef7622", "#315ea8", "#17745a", "#a86508", "#8d5cad", "#4e8098", "#b33a46"];
  let cursor = 0;
  const stops = holdings.map((h, i) => { const start = cursor; cursor += h.weight * 100; return `${colors[i % colors.length]} ${start}% ${cursor}%`; });
  return <div className="allocation-wrap"><div className="donut" style={{ background: `conic-gradient(${stops.join(",")})` }}><div>พอร์ต<br/><strong>100%</strong></div></div><div className="legend-list">{holdings.map((h, i) => <div key={h.asset_id}><i style={{ background: colors[i % colors.length] }} /> <span>{h.symbol}</span><strong>{pct(h.weight)}</strong></div>)}</div></div>;
}

function GoalCards({ goals, analytics, selectedGoalId, onSelect }) {
  const impactMap = Object.fromEntries((analytics?.goal_impacts || []).map((g) => [g.goal_id, g]));
  return <div className="card-grid">{goals.map((goal) => { const impact = impactMap[goal.goal_id]; return <button type="button" onClick={() => onSelect(goal.goal_id)} className={`goal-card${selectedGoalId === goal.goal_id ? " selected" : ""}`} key={goal.goal_id}><div className="spread"><Pill tone={goal.confirmed_with_client ? "green" : "amber"}>{goal.confirmed_with_client ? "ยืนยันแล้ว" : "ต้องยืนยัน"}</Pill><span className="sub-line">{fmtDate(goal.target_date)}</span></div><h3>{goal.label}</h3><div className="goal-amount">฿{fmtTHB(goal.target_amount)}</div><div className="bar target"><span style={{ width: `${Math.min(100, goal.funded_ratio * 100)}%` }} /></div><div className="spread sub-line"><span>มีแล้ว {Math.round(goal.funded_ratio * 100)}%</span><span>{impact ? `โอกาสสำเร็จ ${pct(impact.success_probability)}` : "เลือกเพื่อคำนวณ"}</span></div></button>; })}</div>;
}

function AiBriefPanel({ brief }) {
  if (!brief) return <section className="card span-3"><Spinner /></section>;
  return <section className="card span-3 ai-brief">
    <div className="spread">
      <div><p className="eyebrow">Governed AI · RM copilot</p><h2>สรุปเคสและเตรียมบทสนทนา</h2></div>
      <div className="stack align-end"><Pill tone="amber">Human review required</Pill><span className="sub-line">{brief.live_llm_connected ? "Approved LLM connected" : "Deterministic template fallback"}</span></div>
    </div>
    <div className="ai-why-grid">
      <div><span>Why this client</span><strong>{brief.why_client}</strong></div>
      <div><span>Why this need</span><strong>{brief.why_need}</strong></div>
      <div><span>Why this solution</span><strong>{brief.why_solution}</strong></div>
      <div><span>Why now</span><strong>{brief.why_now}</strong></div>
    </div>
    <div className="coach-grid">
      <div><h3>คำถามที่ควรถาม</h3><ol>{brief.questions.map((question) => <li key={question}>{question}</li>)}</ol></div>
      <div><h3>ร่างข้อความให้ RM ตรวจ</h3><div className="draft-message">{brief.draft_message}</div><p className="sub-line">ห้ามพูด: {brief.do_not_say.join(" · ")}</p></div>
    </div>
    <div className="spread ai-lineage"><span>AI ไม่คำนวณตัวเลขเอง · ใช้ validated calculator เท่านั้น</span><span>{brief.numeric_evidence[0]?.calculationId}</span></div>
  </section>;
}

function SvgLineChart({ points = [], valueKey, secondaryKey, tone = "#ef7622" }) {
  if (!points.length) return <Empty>ยังไม่มีข้อมูลกราฟ</Empty>;
  const values = points.flatMap((point) => [point[valueKey], secondaryKey ? point[secondaryKey] : null]).filter((value) => Number.isFinite(value));
  const minimum = Math.min(...values);
  const maximum = Math.max(...values);
  const range = Math.max(1e-9, maximum - minimum);
  const path = (key) => points.map((point, index) => {
    const x = 12 + index / Math.max(1, points.length - 1) * 696;
    const y = 218 - ((point[key] - minimum) / range) * 198;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  return <svg viewBox="0 0 720 240" className="calc-chart" role="img" aria-label="กราฟจาก calculation result object">
    <line x1="12" x2="708" y1="218" y2="218" className="chart-axis" />
    <polyline points={path(valueKey)} fill="none" stroke={tone} strokeWidth="3" vectorEffect="non-scaling-stroke" />
    {secondaryKey ? <polyline points={path(secondaryKey)} fill="none" stroke="#315ea8" strokeWidth="2" strokeDasharray="7 5" vectorEffect="non-scaling-stroke" /> : null}
  </svg>;
}

function AnnualBars({ rows = [] }) {
  const scale = Math.max(0.01, ...rows.map((row) => Math.abs(row.return)));
  return <div className="annual-bars">{rows.map((row) => <div key={row.year} className="annual-bar-column"><div className="annual-bar-space"><i className={row.return >= 0 ? "positive" : "negative"} style={{ height: `${Math.max(4, Math.abs(row.return) / scale * 82)}%` }} /></div><strong>{pct(row.return)}</strong><span>{row.year}</span></div>)}</div>;
}

function MonthlyHeatmap({ rows = [] }) {
  const years = [...new Set(rows.map((row) => row.year))];
  const byKey = Object.fromEntries(rows.map((row) => [`${row.year}-${row.month}`, row.return]));
  return <div className="heatmap"><div className="heatmap-row heatmap-head"><span>ปี</span>{Array.from({ length: 12 }, (_, i) => <span key={i}>{i + 1}</span>)}</div>{years.map((year) => <div className="heatmap-row" key={year}><strong>{year}</strong>{Array.from({ length: 12 }, (_, i) => { const value = byKey[`${year}-${i + 1}`]; const opacity = Math.min(.9, .18 + Math.abs(value || 0) * 5); return <span title={`${year}-${i + 1}: ${pct(value)}`} style={{ background: value === undefined ? "#eef1f6" : value >= 0 ? `rgba(23,116,90,${opacity})` : `rgba(179,58,70,${opacity})` }}>{value === undefined ? "" : (value * 100).toFixed(0)}</span>; })}</div>)}</div>;
}

function CalculationView({ analytics, compact = false }) {
  if (!analytics) return <Spinner />;
  const m = analytics.metrics;
  const cards = [
    ["expected_return", "ผลตอบแทนคาดหมาย", pct(m.expected_return)], ["annual_volatility", "ความผันผวนต่อปี", pct(m.annual_volatility)],
    ["scenario_cagr", "Scenario CAGR", pct(m.scenario_cagr)], ["max_drawdown", "Scenario MaxDD", pct(m.max_drawdown)],
    ["sharpe", "Sharpe", m.sharpe ?? "—"], ["sortino", "Sortino", m.sortino ?? "—"], ["calmar", "Calmar", m.calmar ?? "—"],
    ["scenario_var95_empirical", "Scenario VaR 95%", pct(m.scenario_var95_empirical)], ["scenario_cvar95_empirical", "Scenario CVaR 95%", pct(m.scenario_cvar95_empirical)],
    ["effective_holdings", "กระจายจริง", m.effective_holdings], ["observation_count", "ข้อมูลแบบจำลอง", `${m.observation_count} เดือน`],
  ];
  return <div className={`calculation-view${compact ? " compact" : ""}`}>
    <div className="spread calc-header"><div><p className="eyebrow">Validated calculation object</p><h2>Calculation</h2><p className="sub-line">{analytics.chart_data?.scenario_label_th}</p></div><div className="calculation-ref"><span>เลขอ้างอิง</span><strong title={analytics.calculation_id}>{friendlyCalcId(analytics.calculation_id, analytics.display_calculation_id)}</strong></div></div>
    <div className="calculation-metrics">{cards.map(([key, label, value]) => { const meta = analytics.metric_metadata?.[key]; return <div key={key}><span>{label}</span><strong>{value}</strong>{meta ? <details><summary>แปลความหมาย · ข้อมูลที่ใช้</summary><p>{meta.meaning_th}</p><small>{meta.formula} · {meta.period} · {meta.source}<br/>{meta.limitation}</small></details> : null}</div>; })}</div>
    <div className="chart-grid">
      <section className="chart-card"><div className="spread"><h3>Growth of THB 1</h3><span className="sub-line">พอร์ต <b className="dot orange"/> · benchmark model <b className="dot blue"/></span></div><SvgLineChart points={analytics.chart_data?.wealth} valueKey="growth_of_one" secondaryKey="benchmark_growth" /></section>
      <section className="chart-card"><h3>Drawdown</h3><SvgLineChart points={analytics.chart_data?.drawdown} valueKey="value" tone="#b33a46" /><p className="sub-line">Peak {fmtDate(analytics.chart_data?.drawdown_event?.peak_date)} · Trough {fmtDate(analytics.chart_data?.drawdown_event?.trough_date)} · Recovery {fmtDate(analytics.chart_data?.drawdown_event?.recovery_date)}</p></section>
      {!compact ? <><section className="chart-card"><h3>Calendar-year return</h3><AnnualBars rows={analytics.chart_data?.annual_returns} /></section><section className="chart-card"><h3>Monthly-return heatmap</h3><MonthlyHeatmap rows={analytics.chart_data?.monthly_returns} /></section><section className="chart-card"><h3>Rolling 12M return</h3><SvgLineChart points={analytics.chart_data?.rolling} valueKey="return_12m" /></section><section className="chart-card"><h3>Rolling volatility</h3><SvgLineChart points={analytics.chart_data?.rolling} valueKey="volatility_12m" tone="#315ea8" /></section></> : null}
    </div>
  </div>;
}

function CorrelationMatrix({ result }) {
  const labels = result?.labels || [];
  return <div className="correlation-wrap"><table className="correlation-table"><thead><tr><th>Asset</th>{labels.map((label) => <th title={label} key={label}>{label.slice(0, 7)}</th>)}</tr></thead><tbody>{labels.map((label, i) => <tr key={label}><th>{label}</th>{(result.matrix[i] || []).map((value, j) => <td key={`${i}-${j}`} style={{ background: `rgba(49,94,168,${.08 + Math.abs(value) * .55})` }}>{value.toFixed(2)}</td>)}</tr>)}</tbody></table></div>;
}

function PortfolioBuilder({ clientId, goalId, portfolio, currentAnalytics, params }) {
  const initial = useMemo(() => Object.fromEntries((portfolio?.holdings || []).filter((h) => h.asset_id !== "CASH:THB").map((h) => [h.asset_id, String((h.weight_bps / 100).toFixed(2).replace(/\.00$/, ""))])), [portfolio]);
  const [draft, setDraft] = useState(initial);
  const [draftAnalytics, setDraftAnalytics] = useState(null);
  const [saved, setSaved] = useState(null);
  const [message, setMessage] = useState("");
  const [query, setQuery] = useState("");
  const [assetClass, setAssetClass] = useState("");
  const [universe, setUniverse] = useState(null);
  const [universeError, setUniverseError] = useState("");
  useEffect(() => { setDraft(initial); setDraftAnalytics(null); setSaved(null); setMessage(""); }, [clientId, initial]);
  useEffect(() => {
    const timer = setTimeout(() => {
      const search = new URLSearchParams({ limit: "120" });
      if (query.trim()) search.set("query", query.trim());
      if (assetClass) search.set("asset_class", assetClass);
      apiGet(`/api/portfolio-universe?${search}`).then((body) => { setUniverse(body); setUniverseError(""); }).catch((error) => setUniverseError(error.message));
    }, 220);
    return () => clearTimeout(timer);
  }, [query, assetClass]);
  useEffect(() => {
    const productId = params.get("addProduct");
    if (productId) setDraft((old) => old[`PRODUCT:${productId}`] !== undefined ? old : { ...old, [`PRODUCT:${productId}`]: "0" });
  }, [params]);
  const rows = Object.entries(draft);
  const total = rows.reduce((sum, [, value]) => sum + (Number(value) || 0), 0);
  const residual = Math.max(0, 100 - total);
  const invalid = total > 100.00001 || rows.some(([, value]) => value === "" || Number(value) < 0);
  const payload = () => rows.map(([asset_id, value]) => ({ asset_id, weight_bps: Math.round(Number(value) * 100) }));
  const labels = Object.fromEntries([...(portfolio?.holdings || []).map((item) => [item.asset_id, item.symbol]), ...(universe?.items || []).map((item) => [item.asset_id, item.name])]);
  async function compare() { try { setMessage(""); setDraftAnalytics(await apiSend("/api/portfolio-analytics", { client_id: clientId, goal_id: goalId || null, holdings: payload() })); } catch (error) { setMessage(error.message); } }
  async function save() { try { setMessage(""); const result = await apiSend(`/api/clients/${clientId}/portfolio-drafts`, { client_id: clientId, goal_id: goalId || null, portfolio_id: portfolio.portfolio_id, draft_id: saved?.draft_id, calculation_id: draftAnalytics?.calculation_id, holdings: payload() }); setSaved(result.draft); setDraftAnalytics(result.analytics); } catch (error) { setMessage(error.message); } }
  function addAsset(assetId) { setDraft((old) => old[assetId] !== undefined ? old : { ...old, [assetId]: "0" }); }
  function applyModel(model) { setDraft(Object.fromEntries(model.weights.map((row) => [row.asset_id, String((row.weight_bps / 100).toFixed(2))]))); setDraftAnalytics(null); setMessage("นำค่าน้ำหนักจาก Model มาเป็น Draft แล้ว — RM ยังแก้ได้ และยังไม่มีการซื้อขาย"); }
  const result = draftAnalytics || currentAnalytics;
  const metrics = result?.metrics;
  return <div className="portfolio-workbench">
    <section className="card asset-universe"><div className="spread"><div><p className="eyebrow">Product universe</p><h2>เลือกสินทรัพย์</h2></div><Pill tone={universe?.market_source === "SETSMART" ? "green" : "amber"}>{universe?.market_source || "Loading"}</Pill></div><div className="field"><label>ค้นหา Symbol / Product</label><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="เช่น PTT, ETF, Bond" /></div><div className="field"><label>Asset class</label><select value={assetClass} onChange={(event) => setAssetClass(event.target.value)}><option value="">ทุกประเภท</option>{(universe?.available_asset_classes || []).map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></div>{universeError ? <ErrorNote message={universeError} /> : <><div className="universe-count">พบ {universe?.total_matches ?? "—"} รายการ · แสดงสูงสุด 120</div><div className="asset-list">{(universe?.items || []).map((asset) => <article key={asset.asset_id}><div><strong>{asset.symbol}</strong><span>{asset.name}</span><small>{asset.asset_class_label} · {asset.provider}</small><small>{asset.price ? `฿${asset.price.toLocaleString()}` : asset.nav ? `NAV ฿${asset.nav.toLocaleString()}` : "ไม่มีราคาที่ contract รองรับ"}</small></div><button className="secondary-button" onClick={() => addAsset(asset.asset_id)} disabled={draft[asset.asset_id] !== undefined}>{draft[asset.asset_id] !== undefined ? "อยู่ใน Draft" : "+ เพิ่ม"}</button></article>)}</div></>}<div className="source-note">SETSMART = ตัวตน/ราคา EOD ที่ contract รองรับ · Bank Product = Demo Catalog/Policy · การอยู่ใน SETSMART ไม่ได้แปลว่าผ่าน approved shelf</div></section>
    <section className="card draft-center"><div className="spread"><div><p className="eyebrow">RM manual control</p><h2>Current → Draft</h2></div><Pill tone={invalid ? "red" : "green"}>{total.toFixed(2)}%</Pill></div><div className="callout callout-info">ต่ำกว่า 100% ถือเป็นเงินสด · เกิน 100% จะ Compare/Save ไม่ได้ · Current ไม่ถูกแก้</div><div className="model-actions">{(currentAnalytics?.model_allocations || []).map((model) => <button key={model.strategy} className="secondary-button" onClick={() => applyModel(model)}>{model.label_th}</button>)}</div><div className="weight-list">{rows.map(([assetId, value]) => { const existing = portfolio.holdings.find((item) => item.asset_id === assetId); return <div className="weight-row" key={assetId}><div><strong>{labels[assetId] || assetId.replace(/^(PRODUCT|SETSMART):/, "")}</strong><div className="sub-line">Current {existing ? pct(existing.weight) : "0.0%"}</div></div><label><span>Draft %</span><input inputMode="decimal" value={value} onChange={(event) => { const next = event.target.value; if (/^\d{0,3}(\.\d{0,2})?$/.test(next)) setDraft((old) => ({ ...old, [assetId]: next })); }} onBlur={() => setDraft((old) => ({ ...old, [assetId]: old[assetId] === "" ? "0" : String(Math.min(100, Number(old[assetId]))) }))} /></label><button className="icon-button" title="นำออกจาก Draft" onClick={() => setDraft((old) => Object.fromEntries(Object.entries(old).filter(([key]) => key !== assetId)))}>×</button></div>; })}</div><div className="sticky-total"><span>รวมสินทรัพย์ <strong>{total.toFixed(2)}%</strong></span><span>เงินสดคงเหลือ <strong>{residual.toFixed(2)}%</strong></span></div><div className="action-row"><button className="secondary-button" onClick={() => { setDraft(initial); setDraftAnalytics(null); }}>กลับเป็น Current</button><Link className="secondary-button link-button" to={`/products?clientId=${clientId}${goalId ? `&goalId=${goalId}` : ""}`}>Product Selection</Link><button className="primary-button" disabled={invalid} onClick={compare}>คำนวณ Draft</button><button className="primary-button orange" disabled={invalid} onClick={save}>บันทึกข้อเสนอ</button></div>{message ? <div className="callout callout-info">{message}</div> : null}{saved ? <div className="callout callout-info">บันทึก {saved.draft_id} แล้ว · Current ยังไม่ถูกแก้ · ต้องผ่าน human approval</div> : null}</section>
    <aside className="card impact-panel"><p className="eyebrow">Immediate impact</p><h2>{draftAnalytics ? "ผลกระทบของ Draft" : "Current (กดคำนวณ Draft เพื่อเทียบ)"}</h2>{metrics ? <><div className="impact-metrics"><div><span>Expected return</span><strong>{pct(metrics.expected_return)}</strong></div><div><span>Volatility</span><strong>{pct(metrics.annual_volatility)}</strong></div><div><span>MaxDD</span><strong>{pct(metrics.max_drawdown)}</strong></div><div><span>CVaR 95</span><strong>{pct(metrics.scenario_cvar95_empirical)}</strong></div><div><span>Sharpe</span><strong>{metrics.sharpe ?? "—"}</strong></div><div><span>Effective holdings</span><strong>{metrics.effective_holdings}</strong></div><div><span>Cash</span><strong>{pct(metrics.residual_cash_weight)}</strong></div></div>{(result.goal_impacts || []).map((goal) => <div className="goal-impact" key={goal.goal_id}><strong>{goal.goal_name}</strong><div>โอกาสสำเร็จ {pct(goal.success_probability)}</div><div>Stress {pct(goal.stress_success_probability)}</div><div>Shortfall ฿{fmtFull(goal.expected_shortfall)}</div></div>)}</> : <Empty>ยังไม่มีผลคำนวณ</Empty>}<details><summary>ข้อจำกัดของผลลัพธ์</summary><p className="sub-line">{result?.assumptions?.limitations?.join(" · ")}</p></details></aside>
    <section className="card calculation-full"><CalculationView analytics={result} /></section>
    <section className="card calculation-full"><div className="spread"><div><p className="eyebrow">Diversification diagnostic</p><h2>Correlation และผู้สร้างความเสี่ยงหลัก</h2></div><span className="sub-line">{result?.correlation?.method}</span></div><div className="risk-analysis-grid"><CorrelationMatrix result={result?.correlation} /><div className="risk-contributors">{(result?.risk_contributors || []).slice(0, 8).map((row) => <div key={row.asset_id}><span>{row.label}</span><strong>{pct(row.risk_share)}</strong></div>)}</div></div></section>
  </div>;
}

function MessageWorkflow({ clientId, goalId }) {
  const [situation, setSituation] = useState("PANIC_MARKET_DROP");
  const [draft, setDraft] = useState(null);
  const [text, setText] = useState("");
  const [reviewed, setReviewed] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  useEffect(() => { setDraft(null); setText(""); setReviewed(false); setNotice(""); setError(""); }, [clientId, goalId]);
  async function createDraft() {
    try {
      setError(""); setNotice(""); setReviewed(false);
      const result = await apiSend(`/api/clients/${clientId}/message-drafts`, { situation, goal_id: goalId || null });
      setDraft(result); setText(result.draft_message);
    } catch (requestError) { setError(requestError.message); }
  }
  async function copyForLine() {
    try { await navigator.clipboard.writeText(text); setNotice("คัดลอกข้อความที่ RM ตรวจแล้ว — ระบบยังไม่ได้ส่ง LINE"); }
    catch { setNotice("คัดลอกอัตโนมัติไม่ได้ กรุณาเลือกข้อความแล้วคัดลอกเอง"); }
  }
  return <div className="message-workflow">
    <section className="card"><p className="eyebrow">Governed AI conversation coach</p><h2>ร่างข้อความตามสถานการณ์</h2><div className="field"><label>สถานการณ์ลูกค้า</label><select value={situation} onChange={(event) => setSituation(event.target.value)}><option value="PANIC_MARKET_DROP">ลูกค้ากังวล/แพนิกเมื่อตลาดลง</option><option value="GOAL_REVIEW">ทบทวน Goal และพอร์ตตามรอบ</option><option value="INACTIVE_REENGAGEMENT">กลับไปดูแลลูกค้าที่ inactive</option></select></div><button className="primary-button" onClick={createDraft}>ให้ AI เตรียมร่าง</button>{error ? <ErrorNote message={error} /> : null}<div className="callout callout-guard">AI ใช้ข้อมูลลูกค้า + calculator + hard gates เพื่อเตรียมเนื้อหา แต่ไม่ส่งเอง ไม่แก้ KYC และไม่สั่งซื้อขาย</div></section>
    <section className="card message-editor-card"><div className="spread"><div><p className="eyebrow">LINE draft</p><h2>RM อ่าน แก้ และตัดสินใจ</h2></div>{draft ? <Pill tone="amber">{draft.status}</Pill> : null}</div>{draft ? <><textarea className="message-editor" value={text} onChange={(event) => { setText(event.target.value); setReviewed(false); }} /><div className="message-review-grid"><div><h3>โครงสร้างข้อมูล</h3><p><strong>สิ่งที่รู้:</strong> {draft.information_design.known}</p><p><strong>ยังไม่รู้:</strong> {draft.information_design.unknown}</p><p><strong>สิ่งที่ทำต่อ:</strong> {draft.information_design.next_action}</p></div><div><h3>ตรวจด้านจิตวิทยา</h3><ul>{draft.psychology_guardrails.map((item) => <li key={item}>{item}</li>)}</ul></div></div><div className="review-checks">{draft.review_checks.map((check) => <span className={check.passed ? "pass" : "review"} key={check.code}>{check.passed ? "✓" : "○"} {check.label_th}</span>)}</div><label className="check-row"><input type="checkbox" checked={reviewed} onChange={(event) => setReviewed(event.target.checked)} /> ผม/ดิฉันอ่านและแก้ข้อความแล้ว เหมาะกับลูกค้ารายนี้</label><div className="action-row"><button className="primary-button" disabled={!reviewed || !text.trim()} onClick={copyForLine}>คัดลอกสำหรับ LINE</button><button className="secondary-button" disabled>ส่ง LINE (ยังไม่เชื่อม)</button><span className="sub-line">Connector: {draft.line_connector}</span></div>{notice ? <div className="callout callout-info">{notice}</div> : null}</> : <Empty>เลือกสถานการณ์แล้วให้ AI เตรียมร่างก่อน</Empty>}</section>
  </div>;
}

export default function ClientWorkspacePage() {
  const { clientId } = useParams();
  const [params, setParams] = useSearchParams();
  const section = params.get("section") || "overview";
  const { data: detail, error, loading } = useApi(`/api/clients/${clientId}`);
  const { data: portfolio } = useApi(`/api/clients/${clientId}/portfolio`);
  const selectedGoalId = params.get("goalId") || detail?.goals?.[0]?.goal_id || null;
  const { data: analytics } = useApi(`/api/clients/${clientId}/portfolio/analytics${selectedGoalId ? `?goal_id=${selectedGoalId}` : ""}`);
  const { data: aiBrief } = useApi(`/api/clients/${clientId}/ai-brief${selectedGoalId ? `?goal_id=${selectedGoalId}` : ""}`);
  if (loading || !portfolio) return <Spinner />;
  if (error) return <ErrorNote message={error} />;
  const client = detail.client;
  const setSection = (key) => { const next = new URLSearchParams(params); next.set("section", key); if (selectedGoalId) next.set("goalId", selectedGoalId); setParams(next); };
  const setGoal = (goalId) => { const next = new URLSearchParams(params); next.set("goalId", goalId); setParams(next); };
  const content = {
    overview: <div className="workspace-grid"><section className="card span-2"><div className="spread"><h2>การจัดสรรปัจจุบัน</h2><span className="sub-line">Position: Synthetic · Market: {portfolio.source.market}</span></div><Allocation holdings={portfolio.holdings} /></section><aside className="card"><h2>Why this client</h2><div className="quote-block" style={{ marginTop: 14 }}><strong>{detail.attention?.headline_th || detail.attention?.headline || "ทบทวนตามรอบ"}</strong><p>{detail.attention?.lane_rationale || "ยังไม่มี mandatory care gate"}</p></div><div className="nba">ต่อไป: {detail.attention?.next_best_action_th || detail.attention?.next_best_action || "ตรวจเป้าหมายและข้อมูลล่าสุด"}</div></aside><section className="card span-3"><h2>Holdings และ P&amp;L สังเคราะห์</h2><div className="table-wrap" style={{ marginTop: 12 }}><table><thead><tr><th>Asset</th><th>ประเภท</th><th className="num">มูลค่า</th><th className="num">น้ำหนัก</th><th className="num">P&amp;L</th><th>Source</th></tr></thead><tbody>{portfolio.holdings.map((h) => <tr key={h.asset_id}><td className="client-name">{h.symbol}</td><td>{titleCase(h.asset_class)}</td><td className="num">฿{fmtFull(h.market_value)}</td><td className="num">{pct(h.weight)}</td><td className="num" style={{ color: h.pnl >= 0 ? "var(--green)" : "var(--red)" }}>฿{fmtFull(h.pnl)}</td><td className="sub-line">{h.position_source}</td></tr>)}</tbody></table></div></section><AiBriefPanel brief={aiBrief} /></div>,
    goals: <><GoalCards goals={detail.goals} analytics={analytics} selectedGoalId={selectedGoalId} onSelect={setGoal} /><div className="callout callout-guard" style={{ marginTop: 16 }}>Goal ที่ยังไม่ยืนยันจะไม่เปิดทางให้ระบบเลือกผลิตภัณฑ์ ต้องถามลูกค้าให้ครบก่อน</div></>,
    portfolio: <PortfolioBuilder clientId={clientId} goalId={selectedGoalId} portfolio={portfolio} currentAnalytics={analytics} params={params} />,
    quant: <div className="stack"><section className="card"><CalculationView analytics={analytics} /></section><section className="card"><div className="spread"><div><p className="eyebrow">Calculation lineage</p><h2>ที่มาและข้อจำกัด</h2></div><div className="calculation-ref"><span>เลขอ้างอิง</span><strong title={analytics?.calculation_id}>{friendlyCalcId(analytics?.calculation_id, analytics?.display_calculation_id)}</strong></div></div><div className="lineage-grid"><div><span>วิธี</span><strong>{analytics?.method}</strong></div><div><span>ข้อมูล ณ</span><strong>{analytics?.context?.asOf}</strong></div><div><span>Covariance</span><strong>{analytics?.assumptions?.covariance}</strong></div><div><span>ความถี่ / จำนวน</span><strong>{analytics?.assumptions?.observation_frequency} · {analytics?.assumptions?.observation_count}</strong></div></div><div className="callout callout-guard">กราฟชุดนี้เป็น deterministic model scenario เพื่อเปรียบเทียบ Current/Draft ด้วยกติกาเดียวกัน ไม่ใช่ผลตอบแทนย้อนหลังและไม่ใช่การพยากรณ์</div></section></div>,
    activity: <div className="workspace-grid"><section className="card span-2"><h2>กิจกรรมลูกค้า</h2><div className="mini-metrics"><div><span>สถานะ</span><strong>{titleCase(detail.activity?.status)}</strong></div><div><span>กิจกรรมล่าสุด</span><strong>{fmtDate(detail.activity?.last_activity_on)}</strong></div><div><span>ครั้งล่าสุด</span><strong>{titleCase(detail.activity?.last_activity_kind)}</strong></div><div><span>เงินสดว่าง</span><strong>฿{fmtTHB(detail.activity?.idle_cash)}</strong></div></div></section><aside className="card"><Pill tone={ACTIVITY_TONE[detail.activity?.status] || "muted"}>{titleCase(detail.activity?.status)}</Pill><p>{detail.activity?.reengagement_reason || "ยัง active และไม่มีเหตุ re-engage เพิ่ม"}</p><p className="sub-line">นับจาก deposit / withdrawal / trade ของลูกค้า ไม่ใช่จากสาย outbound ของ RM</p></aside></div>,
    kyc: <div className="workspace-grid"><section className="card span-2"><h2>KYC และ Suitability</h2><div className="mini-metrics"><div><span>KYC</span><strong>{titleCase(detail.kyc?.kyc_status || "missing")}</strong></div><div><span>หมดอายุ</span><strong>{fmtDate(detail.kyc?.expires_on)}</strong></div><div><span>Suitability</span><strong>{fmtDate(detail.kyc?.suitability_expires_on)}</strong></div><div><span>AML workflow</span><strong>{titleCase(detail.kyc?.aml_risk_rating)}</strong></div></div></section><aside className="card"><h2>เอกสารที่ขาด</h2>{detail.kyc?.missing_documents?.length ? detail.kyc.missing_documents.map((d) => <div className="callout callout-error" key={d}>{d}</div>) : <div className="callout callout-info">ไม่มีรายการขาดใน synthetic workflow</div>}<Link to={`/kyc?clientId=${clientId}`}>เปิด KYC queue →</Link></aside></div>,
    tasks: <><div className="card"><h2>งานและการส่งต่อ</h2><div className="action-timeline"><div><b>1</b><span>ตรวจข้อมูลและ Goal Contract</span></div><div><b>2</b><span>เปรียบเทียบ Current / Draft / Product</span></div><div><b>3</b><span>AI เตรียมคำอธิบายและร่างข้อความ</span></div><div><b>4</b><span>RM อ่าน แก้ และเลือกช่องทาง · ส่ง specialist เมื่อจำเป็น</span></div></div></div><MessageWorkflow clientId={clientId} goalId={selectedGoalId} /></>,
    audit: <div className="card"><h2>Audit context</h2><pre>{JSON.stringify({ ...detail.context, selectedGoalId, calculationId: analytics?.calculation_id }, null, 2)}</pre><p className="sub-line">Client/KYC เป็น synthetic · Product catalog เป็น demo · Market source แสดงแยก · Live bank systems ไม่ได้เชื่อม</p></div>,
  }[section];
  return <WorkspaceProvider value={{ ...detail.context, selectedGoalId, calculationId: analytics?.calculation_id }}><div className="page-enter">
    <PageHead eyebrow="Client Record" title={client.name} lede={`Why this client, why this need, why this solution, and why now? · ${client.client_id}`}><Link className="secondary-button link-button" to="/clients">เปลี่ยนลูกค้า</Link></PageHead>
    <div className="client-strip"><div><span>AUM</span><strong>฿{fmtTHB(client.aum)}</strong></div><div><span>ลงทุนได้</span><strong>฿{fmtTHB(client.investable_cash)}</strong></div><div><span>Risk</span><strong>{titleCase(client.risk_profile)}</strong></div><div><span>KYC</span><Pill tone={KYC_TONE[detail.kyc?.kyc_status] || "muted"}>{titleCase(detail.kyc?.kyc_status)}</Pill></div><div><span>Data</span><strong>Synthetic + {portfolio.source.market}</strong></div></div>
    <div className="subnav">{SECTIONS.map(([key, label]) => <button className={section === key ? "active" : ""} onClick={() => setSection(key)} key={key}>{label}</button>)}</div>
    {content}
  </div></WorkspaceProvider>;
}
