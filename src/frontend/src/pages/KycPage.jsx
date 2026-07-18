import { Link, useSearchParams } from "react-router-dom";
import { useState } from "react";
import { useApi, fmtDate, titleCase } from "../lib/api.js";
import { Empty, ErrorNote, KYC_TONE, Metric, PageHead, Pill, Spinner } from "../components/Bits.jsx";

const FILTERS = [["", "ทั้งหมด"], ["overdue", "หมดอายุ"], ["missing", "เอกสารขาด"], ["due_soon", "ใกล้ครบกำหนด"], ["valid", "พร้อม"]];
export default function KycPage() {
  const [params] = useSearchParams();
  const [status, setStatus] = useState(params.get("view") === "blocked" ? "overdue" : "");
  const { data, error, loading } = useApi(`/api/kyc${status ? `?status=${status}` : ""}`);
  const { data: all } = useApi("/api/kyc");
  if (loading) return <Spinner />;
  if (error) return <ErrorNote message={error} />;
  const summary = all?.summary || data.summary;
  return <div className="page-enter"><PageHead eyebrow="Operational queue" title="KYC" lede="ใช้เป็นคิวงานรวมเท่านั้น รายละเอียดและผลกระทบต่อคำแนะนำต้องย้อนกลับไปที่ Client Record" />
    <div className="metric-grid"><Metric label="คำแนะนำถูกบล็อก" value={summary.advice_blocked} sub="AUM ข้าม hard gate ไม่ได้" tone="inverted"/><Metric label="KYC หมดอายุ" value={summary.by_status.overdue}/><Metric label="เอกสารขาด" value={summary.by_status.missing}/><Metric label="ครบกำหนดใน 60 วัน" value={summary.renewals_due_60d}/></div>
    <div className="chip-row">{FILTERS.map(([key, label]) => <button className={`chip${status === key ? " is-active" : ""}`} onClick={() => setStatus(key)} key={key}>{label}</button>)}</div>
    {!data.rows.length ? <Empty>ไม่มีรายการในคิวนี้</Empty> : <div className="table-wrap"><table><thead><tr><th>ลูกค้า</th><th>สถานะ</th><th>ครบกำหนด</th><th>สิ่งที่ขาด</th><th>งานที่ต้องทำ</th><th>Client Record</th></tr></thead><tbody>{data.rows.map((row) => <tr key={row.client_id}><td><div className="client-name">{row.client_name}</div><div className="sub-line">{row.client_id} · {row.segment}</div></td><td><Pill tone={KYC_TONE[row.status]}>{titleCase(row.status)}</Pill>{row.advice_blocked ? <div className="sub-line" style={{ color: "var(--red)" }}>Advice blocked</div> : null}</td><td>{fmtDate(row.expires_on)}<div className="sub-line">{row.days_to_expiry === null ? "ไม่มีวันที่" : row.days_to_expiry < 0 ? `${Math.abs(row.days_to_expiry)} วันเกินกำหนด` : `อีก ${row.days_to_expiry} วัน`}</div></td><td>{row.missing_documents.length ? row.missing_documents.join(", ") : row.suitability_overdue ? "Suitability หมดอายุ" : "—"}</td><td>{row.action}</td><td><Link className="primary-button link-button" to={`/clients/${row.client_id}?section=kyc`}>เปิดเอกสาร</Link></td></tr>)}</tbody></table></div>}
  </div>;
}
