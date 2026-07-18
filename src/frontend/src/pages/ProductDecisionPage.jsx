import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { apiGet, apiSend, useApi, fmtDate, fmtFull, fmtTHB, titleCase } from "../lib/api.js";
import { Empty, ErrorNote, PageHead, Pill, Spinner } from "../components/Bits.jsx";

const pct = (v) => v === null || v === undefined ? "—" : `${(v * 100).toFixed(1)}%`;

function ProductDrawer({ productId, onClose }) {
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => { if (productId) apiGet(`/api/products/${productId}`).then(setDetail).catch((e) => setError(e.message)); }, [productId]);
  if (!productId) return null;
  const p = detail?.product;
  return <div className="drawer-backdrop" onClick={onClose}><aside className="drawer" onClick={(e) => e.stopPropagation()}><button className="drawer-close" onClick={onClose}>×</button>{error ? <ErrorNote message={error} /> : !p ? <Spinner /> : <><p className="eyebrow">Product detail · Demo Catalog</p><h2>{p.name}</h2><div className="chip-row"><Pill tone="blue">{titleCase(p.product_type)}</Pill><Pill tone="amber">Risk {titleCase(p.risk_level)}</Pill><Pill tone="muted">{p.currency}</Pill></div><h3>คืออะไร</h3><p>{p.description}</p><h3>ประโยคช่วย RM อธิบาย</h3><div className="quote-block">ผลิตภัณฑ์นี้อาจช่วยเป้าหมายที่เลือกได้ภายใต้สมมติฐาน แต่ผลตอบแทนไม่รับประกัน และต้องดูระยะเวลา สภาพคล่อง และความเสี่ยงก่อนตัดสินใจ</div><dl className="detail-list"><div><dt>Minimum</dt><dd>฿{fmtFull(p.min_investment)}</dd></div><div><dt>Liquidity</dt><dd>{p.liquidity_days} วัน</dd></div><div><dt>Indicative assumption</dt><dd>{p.indicative_return_pct}% ต่อปี</dd></div><div><dt>Fees</dt><dd>{p.fees}</dd></div><div><dt>Factsheet</dt><dd>{p.factsheet}</dd></div><div><dt>Source</dt><dd>{p.source}</dd></div></dl><div className="callout callout-guard">Demo Bank Policy — ต้องยืนยันกับ Compliance ก่อนใช้จริง</div></>}</aside></div>;
}

export default function ProductDecisionPage() {
  const [params, setParams] = useSearchParams();
  const { data: clientsData, error, loading } = useApi("/api/clients");
  const clientId = params.get("clientId") || "";
  const goalId = params.get("goalId") || "";
  const client = useMemo(() => clientsData?.clients?.find((c) => c.client_id === clientId), [clientsData, clientId]);
  const [decision, setDecision] = useState(null);
  const [decisionError, setDecisionError] = useState(null);
  const [contribution, setContribution] = useState("0");
  const [confirmed, setConfirmed] = useState(true);
  const [drawer, setDrawer] = useState(null);
  useEffect(() => { setDecision(null); setDecisionError(null); setConfirmed(client?.goals?.find((g) => g.goal_id === goalId)?.confirmed ?? true); }, [clientId, goalId, client]);
  useEffect(() => {
    if (!clientId || !goalId || !client) return;
    setDecision(null); setDecisionError(null);
    apiSend("/api/goal-decisions/evaluate", { client_id: clientId, goal_id: goalId, goal_contract: { client_confirmed: confirmed, planned_contribution: Number(contribution) || 0 } }).then(setDecision).catch((e) => setDecisionError(e.message));
  }, [clientId, goalId, confirmed, contribution, client]);
  if (loading) return <Spinner />;
  if (error) return <ErrorNote message={error} />;
  const updateParam = (key, value) => { const next = new URLSearchParams(params); if (value) next.set(key, value); else next.delete(key); if (key === "clientId") next.delete("goalId"); setParams(next); };
  const goal = client?.goals?.find((g) => g.goal_id === goalId);
  const alternatives = decision?.alternatives || [];
  const feasible = alternatives.filter((a) => a.feasible);
  const blocked = alternatives.filter((a) => !a.feasible);
  return <div className="page-enter">
    <PageHead eyebrow="Goal-conditioned product decision" title="Product" lede="ระบบไม่เริ่มจากคำว่า ‘อยากได้ 6% ความเสี่ยงต่ำ’ อย่างเดียว ต้องผูก Client + Goal Contract + Hard Gates ก่อน และไม่เลือกผู้ชนะด้วยคะแนนทึบ" />
    <div className="decision-layout"><aside className="card sticky-panel"><div className="field"><label>เลือกลูกค้า</label><select value={clientId} onChange={(e) => updateParam("clientId", e.target.value)}><option value="">— เลือกลูกค้า —</option>{clientsData.clients.map((c) => <option value={c.client_id} key={c.client_id}>{c.name} · {c.client_id}</option>)}</select></div><div className="field"><label>เลือกเป้าหมาย</label><select disabled={!client} value={goalId} onChange={(e) => updateParam("goalId", e.target.value)}><option value="">— เลือก Goal Contract —</option>{client?.goals.map((g) => <option value={g.goal_id} key={g.goal_id}>{g.label}</option>)}</select></div>{client ? <div className="client-summary"><div><span>AUM</span><strong>฿{fmtTHB(client.aum)}</strong></div><div><span>ลงทุนได้</span><strong>฿{fmtTHB(client.investable_cash)}</strong></div><div><span>KYC</span><strong>{titleCase(client.kyc_status)}</strong></div></div> : null}{goal ? <><div className="goal-contract"><h3>{goal.label}</h3><div>เป้าหมาย ฿{fmtTHB(goal.target_amount)}</div><div>วันที่ {fmtDate(goal.target_date)}</div><div>มีแล้ว {Math.round(goal.funded_ratio * 100)}%</div></div><label className="check-row"><input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} /> ลูกค้ายืนยัน Goal Contract</label><div className="field"><label>ออมเพิ่มต่อเดือน (บาท)</label><input inputMode="numeric" value={contribution} onChange={(e) => /^\d*$/.test(e.target.value) && setContribution(e.target.value)} /></div></> : null}<div className="source-note">Client/KYC: Synthetic workflow<br/>Product: Demo catalog/policy<br/>Market: SETSMART เมื่อ contract รองรับ</div></aside>
      <main className="decision-main">{!client || !goal ? <Empty>เลือกลูกค้าและเป้าหมายก่อน ระบบจึงจะกรอง Product และคำนวณผลต่อ Goal ได้</Empty> : decisionError ? <ErrorNote message={decisionError} /> : !decision ? <Spinner /> : decision.status === "NEED_GOAL_CLARIFICATION" ? <div className="card"><Pill tone="amber">NEED GOAL CLARIFICATION</Pill><h2 style={{ marginTop: 12 }}>{decision.message}</h2><div className="stack" style={{ marginTop: 14 }}>{decision.clarification_questions.map((q) => <div className="callout callout-guard" key={q.field}>{q.question}</div>)}</div></div> : <><div className="goal-result-strip"><div><span>Goal</span><strong>{decision.goal_contract.goal_name}</strong></div><div><span>Current success</span><strong>{pct(decision.current_goal_impact.success_probability)}</strong></div><div><span>Current shortfall</span><strong>฿{fmtTHB(decision.current_goal_impact.expected_shortfall)}</strong></div><div><span>Calculation</span><strong>{decision.calculation_id}</strong></div></div><div className="callout callout-info">Pareto set แสดงหลาย trade-off ไม่มีคำว่า “winner” อัตโนมัติ · RM เป็นผู้ตัดสินใจ</div><h2 style={{ marginTop: 20 }}>ทางเลือกที่ผ่าน Hard Gates</h2><div className="product-grid">{feasible.map((a) => <article className={`product-card${decision.pareto_alternative_ids.includes(a.alternative_id) ? " pareto" : ""}`} key={a.alternative_id}><div className="spread"><Pill tone={a.category === "KEEP_CASH" ? "blue" : a.category === "PORTFOLIO_ADJUSTMENT_PREFERRED" ? "amber" : "green"}>{a.category.replace(/_/g, " ")}</Pill>{decision.pareto_alternative_ids.includes(a.alternative_id) ? <span className="pareto-label">Pareto</span> : null}</div><h3>{a.name}</h3><p>{a.trade_off}</p><div className="product-impact"><div><span>Goal success</span><strong>{pct(a.goal_impact.success_probability)}</strong></div><div><span>Shortfall</span><strong>฿{fmtTHB(a.goal_impact.expected_shortfall)}</strong></div><div><span>Stress success</span><strong>{pct(a.goal_impact.stress_success_probability)}</strong></div></div><div className="action-row">{a.product ? <button className="secondary-button" onClick={() => setDrawer(a.alternative_id)}>ดูรายละเอียด</button> : null}{a.category === "PORTFOLIO_ADJUSTMENT_PREFERRED" ? <Link className="primary-button link-button" to={a.href}>เปิดจัดพอร์ต</Link> : a.product ? <Link className="primary-button link-button" to={`/clients/${clientId}?section=portfolio&goalId=${goalId}&addProduct=${a.alternative_id}`}>เพิ่มเข้า Draft</Link> : null}</div></article>)}</div>{blocked.length ? <details className="card blocked-products"><summary>ดู Product ที่ไม่ผ่าน ({blocked.length})</summary><div className="stack" style={{ marginTop: 14 }}>{blocked.map((a) => <div className="blocked-row" key={a.alternative_id}><div><strong>{a.name}</strong><div className="sub-line">{a.hard_gate_reasons.join(" · ")}</div></div><Pill tone="red">INFEASIBLE</Pill></div>)}</div></details> : null}</>}</main>
    </div><ProductDrawer productId={drawer} onClose={() => setDrawer(null)} />
  </div>;
}
