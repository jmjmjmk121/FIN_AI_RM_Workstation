import { useMemo } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useApi, fmtDate, fmtFull, fmtTHB, titleCase } from "../lib/api.js";
import { ACTIVITY_TONE, ErrorNote, Metric, PageHead, Pill, Spinner } from "../components/Bits.jsx";

const FILTERS = [
  ["all", "ทั้งหมด"],
  ["review_today", "ทบทวนวันนี้"],
  ["active_trading", "Active Trading"],
  ["active_cash_flow", "Active Cash Flow"],
  ["holding_only", "Holding Only"],
  ["active", "Active รวม"],
  ["cooling", "Cooling"],
  ["at_risk", "Dormant / Inactive"],
];

const KIND_TH = { deposit: "ฝากเงิน", withdrawal: "ถอนเงิน", trade: "ซื้อขาย" };
const INVESTMENT_TH = {
  active_trading: "Active Trading",
  active_cash_flow: "Active Cash Flow",
  holding_only: "Holding Only",
  no_recent_investment_activity: "No Recent Activity",
};

function matches(row, filter) {
  if (filter === "all") return true;
  if (filter === "at_risk") return row.status === "dormant" || row.status === "inactive";
  if (["active", "cooling", "dormant", "inactive"].includes(filter)) return row.status === filter;
  return row.investment_activity === filter;
}

function ProductOpportunity({ item }) {
  return <article className="ai-opportunity">
    <div className="spread"><div><div className="client-name">{item.client_name}</div><div className="sub-line">{item.goal_name}</div></div><Pill tone="blue">AI prepared</Pill></div>
    <p>{item.why_now}</p>
    {item.product_candidates.length ? <div className="candidate-list">{item.product_candidates.map((product) => <span key={product.product_id}>{product.name}</span>)}</div> : <div className="callout callout-guard">{item.next_step}</div>}
    <div className="spread opportunity-footer"><span>{INVESTMENT_TH[item.investment_activity]}</span><Link to={item.href}>ตรวจ Product และ Gate →</Link></div>
  </article>;
}

export default function DashboardPage() {
  const [params, setParams] = useSearchParams();
  const filter = params.get("activity") || "all";
  const { data, error, loading } = useApi("/api/dashboard");
  const rows = useMemo(() => {
    if (!data) return [];
    const reviewIds = new Set((data.daily_review_candidates || []).map((row) => row.client_id));
    const reviewRank = new Map((data.daily_review_candidates || []).map((row, index) => [row.client_id, index]));
    return data.active_clients.filter((row) => filter === "review_today" ? reviewIds.has(row.client_id) : matches(row, filter)).sort((a, b) => {
      if (filter === "review_today") return (reviewRank.get(a.client_id) ?? 999) - (reviewRank.get(b.client_id) ?? 999);
      const left = a.last_activity_on ? new Date(a.last_activity_on).getTime() : 0;
      const right = b.last_activity_on ? new Date(b.last_activity_on).getTime() : 0;
      return filter === "at_risk" ? left - right : right - left;
    });
  }, [data, filter]);
  if (loading) return <Spinner />;
  if (error) return <ErrorNote message={error} />;
  const ai = data.ai_product_opportunities;
  const marketLive = data.data_sources.market_data === "LIVE";
  const marketReason = data.data_sources.market_degraded_reason?.includes("401")
    ? "API key ถูก SETSMART ปฏิเสธ (HTTP 401) กรุณาใช้ rotated key ที่ยังใช้งานได้"
    : data.data_sources.market_degraded_reason;
  return <div className="page-enter active-dashboard">
    <PageHead eyebrow="Workbench A · Client activity" title="Dashboard: Active Clients" lede="ดูสถานะลูกค้าจากรายการฝาก ถอน ซื้อขาย และการถือครองจริง แล้วให้ AI เตรียม Product conversation จาก Goal Contract และ hard gates">
      <Link className="secondary-button link-button" to="/clients">เปิด Client Book</Link>
    </PageHead>
    <div className="source-strip"><span>Market Data: SETSMART {marketLive ? "LIVE" : "FIXTURE FALLBACK"}</span><span>Client Book: {data.summary.clients} Synthetic Client 360</span><span>Product shelf: Demo Bank Catalog</span><span>AI: Governed orchestration · Human review</span></div>
    {marketReason ? <div className="callout callout-error market-fallback-note">SETSMART live ยังใช้ไม่ได้: {marketReason} · ระบบจึงใช้ fixture ที่ติดป้ายชัดเจนและไม่สร้างข้อมูลตลาดขึ้นเอง</div> : null}
    <div className="metric-grid activity-metrics">{data.cards.map((card, index) => <Link className="metric-link" to={card.href} key={card.id}><Metric label={card.title} value={card.value} sub={card.detail} tone={index === 0 ? "inverted" : undefined} /></Link>)}</div>

    <section className="card today-review-queue">
      <div className="spread"><div><p className="eyebrow">Today in 5 minutes</p><h2>AI คัดเคสให้ RM ทบทวนก่อน</h2></div><div className="queue-count"><strong>{data.summary.review_today}</strong><span>เคสทบทวนวันนี้ · แสดง Top {data.summary.top_visible}</span></div></div>
      <div className="today-review-grid">{data.top_attention.map((item, index) => <article key={item.client_id} className={`today-review-item lane-${item.lane}`}>
        <div className="spread"><span className="queue-rank">{index + 1}</span><Pill tone={item.lane === "care" ? "care" : "green"}>{item.lane.toUpperCase()}</Pill></div>
        <Link className="client-name" to={`/clients/${item.client_id}`}>{item.client_name}</Link>
        <p>{item.headline_th}</p><div className="next-step">ต่อไป: {item.next_best_action_th}</div>
      </article>)}</div>
      <div className="queue-policy-note"><span>Client Book <strong>{data.summary.clients}</strong> ราย</span><span>Attention backlog <strong>{data.summary.attention_backlog ?? "—"}</strong> ราย</span><span>Daily screening <strong>{data.summary.care} Care + {data.summary.growth} Growth</strong></span><span>{data.review_policy?.note_th || "เป็นชุดเคสให้ RM ทบทวน ไม่ใช่เป้าหมายให้ติดต่อลูกค้าทุกราย"}</span></div>
    </section>

    <div className="dashboard-main-grid">
      <section className="card activity-monitor">
        <div className="spread"><div><p className="eyebrow">Investment + relationship activity</p><h2>สถานะลูกค้าใน Book</h2></div><span className="sub-line">แสดง {Math.min(rows.length, 14)} จาก {rows.length} ราย</span></div>
        <div className="chip-row dashboard-chips">{FILTERS.map(([key, label]) => <button key={key} className={`chip${filter === key ? " is-active" : ""}`} onClick={() => { const next = new URLSearchParams(params); next.set("activity", key); setParams(next); }}>{label}</button>)}</div>
        <div className="table-wrap activity-table"><table><thead><tr><th>ลูกค้า / Engagement</th><th>กิจกรรมล่าสุด</th><th>ประวัติ Deposit / Withdrawal / Trade</th><th className="num">AUM / เงินสด</th><th>AI Next Step</th></tr></thead><tbody>{rows.slice(0, 14).map((row) => {
          const goal = row.primary_goal;
          const blocked = row.permitted_action === "CONFIRM_DATA" || row.permitted_action === "DO_NOT_CONTACT" || row.permitted_action === "CHECK_CONTACT_LOCK";
          const nextHref = blocked ? `/clients/${row.client_id}?section=kyc` : goal?.confirmed ? `/products?clientId=${row.client_id}&goalId=${goal.goal_id}` : `/clients/${row.client_id}?section=goals`;
          return <tr key={row.client_id}><td><Link className="client-name" to={`/clients/${row.client_id}`}>{row.client_name}</Link><div className="activity-pills"><Pill tone={ACTIVITY_TONE[row.status] || "muted"}>{titleCase(row.status)}</Pill><span>{INVESTMENT_TH[row.investment_activity]}</span></div><div className="sub-line">Relationship: {titleCase(row.relationship_activity)}</div></td><td><strong>{KIND_TH[row.last_activity_kind] || "ไม่มีข้อมูล"}</strong><div className="sub-line">{fmtDate(row.last_activity_on)} · {row.months_since_activity ?? "—"} เดือน</div></td><td><div className="event-dates"><span><b>D</b>{fmtDate(row.last_deposit_on)}</span><span><b>W</b>{fmtDate(row.last_withdrawal_on)}</span><span><b>T</b>{fmtDate(row.last_trade_on)}</span></div></td><td className="num"><strong>฿{fmtTHB(row.aum)}</strong><div className="sub-line">ลงทุนได้ ฿{fmtTHB(row.idle_cash)}</div></td><td><div className={`next-step ${blocked ? "blocked" : ""}`}>{blocked ? "ยืนยันข้อมูลก่อน" : row.next_action}</div><Link to={nextHref}>{blocked ? "เปิด Gate" : goal?.confirmed ? "ให้ AI กรอง Product" : "ยืนยัน Goal"} →</Link></td></tr>;
        })}</tbody></table></div>
        <p className="table-note">Activity มาจากวันที่ transaction สังเคราะห์ ไม่ได้นับ outbound call ของ RM · Holding Only ไม่ถูกตีความว่า churn อัตโนมัติ · Reactivated ต้องใช้ event history จากระบบธนาคารซึ่งยังไม่เชื่อม</p>
      </section>

      <aside className="card ai-opportunity-panel">
        <div className="spread"><div><p className="eyebrow">Workbench B · Goal-conditioned</p><h2>AI Product Next Step</h2></div><Pill tone="green">{ai.summary.ready_for_rm_review} พร้อมให้ตรวจ</Pill></div>
        <p className="sub-line">AI เลือก moment จาก activity แล้วใช้ Goal → Hard Gates → Calculator → Product alternatives ไม่มีการเลือก “ผู้ชนะ” หรือส่งหาลูกค้าอัตโนมัติ</p>
        <div className="opportunity-list">{ai.items.slice(0, 5).map((item) => <ProductOpportunity item={item} key={`${item.client_id}-${item.goal_id}`} />)}</div>
        <div className="ai-guard-summary"><span>ต้องยืนยัน Goal <strong>{ai.summary.needs_goal_confirmation}</strong></span><span>ติด Hard Gate <strong>{ai.summary.blocked_by_hard_gate}</strong></span></div>
        <Link className="primary-button link-button opportunity-cta" to="/products">เปิด Goal-Based Product Decision</Link>
      </aside>
    </div>

    <section className="activity-definitions"><div><strong>Active Trading</strong><span>มี trade ใน 6 เดือน</span></div><div><strong>Active Cash Flow</strong><span>มี deposit/withdraw ใน 6 เดือน แม้ไม่มี trade</span></div><div><strong>Holding Only</strong><span>ยังถือสินทรัพย์ แต่ไม่มี transaction ล่าสุด</span></div><div><strong>Dormant / Inactive</strong><span>ต้องตรวจ consent, ownership, KYC และ open task ก่อน re-engage</span></div></section>
  </div>;
}
