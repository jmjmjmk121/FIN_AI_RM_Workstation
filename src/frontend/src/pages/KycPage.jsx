import { Link, useSearchParams } from "react-router-dom";
import { useState } from "react";
import { useApi, fmtDate, titleCase } from "../lib/api.js";
import { Empty, ErrorNote, KYC_TONE, Metric, PageHead, Pill, Spinner } from "../components/Bits.jsx";

const FILTERS = [["", "ทั้งหมด"], ["overdue", "หมดอายุ"], ["missing", "เอกสารขาด"], ["due_soon", "ใกล้ครบกำหนด"], ["valid", "พร้อม"]];

const AML_TONE = { high: "red", medium: "amber", low: "green", unknown: "muted" };
const AML_LABEL = { high: "สูง", medium: "กลาง", low: "ต่ำ", unknown: "ไม่ทราบ" };
const AML_FILL = { high: "var(--red)", medium: "var(--amber)", low: "var(--green)", unknown: "var(--muted)" };

/** Compact indicative-score meter, coloured by the rating of record. */
function ScoreMeter({ score, tone }) {
  return (
    <div className="bar" style={{ minWidth: 72 }}>
      <span style={{ width: `${score}%`, background: AML_FILL[tone] || "var(--blue)" }} />
    </div>
  );
}

function AmlDetail({ aml }) {
  const { factors, screening } = aml;
  return (
    <div style={{ padding: "12px 4px 4px", display: "grid", gap: 12 }}>
      <div style={{ display: "grid", gap: 8 }}>
        {factors.map((f) => (
          <div key={f.key} style={{ display: "grid", gridTemplateColumns: "150px 90px 1fr", gap: 10, alignItems: "center" }}>
            <div>
              <div style={{ fontWeight: 700 }}>{f.label_th}</div>
              <div className="sub-line">น้ำหนัก {Math.round(f.weight * 100)}% · {f.data_source === "SYNTHETIC_PROXY" ? "proxy" : "ข้อมูลจริง"}</div>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <div className="bar" style={{ flex: 1 }}><span style={{ width: `${f.score}%` }} /></div>
              <span className="sub-line" style={{ minWidth: 22 }}>{f.score}</span>
            </div>
            <div className="sub-line" style={{ fontWeight: 400 }}>{f.rationale_th}</div>
          </div>
        ))}
      </div>
      <div className="sub-line" style={{ fontWeight: 400, color: "var(--muted)" }}>
        คัดกรอง Sanctions/PEP: {screening.sanctions_pep_status} · connector {screening.connector} · อ้างอิงรายชื่อ {screening.lists_reference.join(", ")}.
        <br />{screening.note_th}
      </div>
    </div>
  );
}

export default function KycPage() {
  const [params] = useSearchParams();
  const [status, setStatus] = useState(params.get("view") === "blocked" ? "overdue" : "");
  const [openId, setOpenId] = useState(null);
  const { data, error, loading } = useApi(`/api/kyc${status ? `?status=${status}` : ""}`);
  const { data: all } = useApi("/api/kyc");
  if (loading) return <Spinner />;
  if (error) return <ErrorNote message={error} />;
  const summary = all?.summary || data.summary;
  return <div className="page-enter"><PageHead eyebrow="Operational queue" title="KYC" lede="ใช้เป็นคิวงานรวมเท่านั้น รายละเอียดและผลกระทบต่อคำแนะนำต้องย้อนกลับไปที่ Client Record · คะแนน AML สี่ปัจจัยเป็นตัวช่วยอธิบาย ไม่แทนที่ AML rating ของระบบ" />
    <div className="metric-grid"><Metric label="คำแนะนำถูกบล็อก" value={summary.advice_blocked} sub="AUM ข้าม hard gate ไม่ได้" tone="inverted"/><Metric label="KYC หมดอายุ" value={summary.by_status.overdue}/><Metric label="เอกสารขาด" value={summary.by_status.missing}/><Metric label="ครบกำหนดใน 60 วัน" value={summary.renewals_due_60d}/><Metric label="ต้องคัดกรอง AML" value={summary.aml_screening_required} sub={`ความเสี่ยงสูง ${summary.high_aml_risk}`}/></div>
    <div className="chip-row">{FILTERS.map(([key, label]) => <button className={`chip${status === key ? " is-active" : ""}`} onClick={() => setStatus(key)} key={key}>{label}</button>)}</div>
    {!data.rows.length ? <Empty>ไม่มีรายการในคิวนี้</Empty> : <div className="table-wrap"><table><thead><tr><th>ลูกค้า</th><th>สถานะ</th><th>AML</th><th>ครบกำหนด</th><th>สิ่งที่ขาด</th><th>งานที่ต้องทำ</th><th>Client Record</th></tr></thead><tbody>{data.rows.map((row) => {
      const aml = row.aml;
      const tone = AML_TONE[aml.rating_of_record] || "muted";
      const isOpen = openId === row.client_id;
      return [
        <tr key={row.client_id}>
          <td><div className="client-name">{row.client_name}</div><div className="sub-line">{row.client_id} · {row.segment}</div></td>
          <td><Pill tone={KYC_TONE[row.status]}>{titleCase(row.status)}</Pill>{row.advice_blocked ? <div className="sub-line" style={{ color: "var(--red)" }}>Advice blocked</div> : null}</td>
          <td>
            <button className="chip" style={{ padding: "2px 8px", marginBottom: 4 }} onClick={() => setOpenId(isOpen ? null : row.client_id)}>
              <Pill tone={tone}>{AML_LABEL[aml.rating_of_record] || aml.rating_of_record}</Pill> {isOpen ? "▾" : "▸"}
            </button>
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}><ScoreMeter score={aml.score} tone={tone} /><span className="sub-line">{aml.score}/100</span></div>
            {aml.screening.requires_manual_screening ? <div className="sub-line" style={{ color: "var(--red)" }}>ต้องคัดกรอง</div> : null}
          </td>
          <td>{fmtDate(row.expires_on)}<div className="sub-line">{row.days_to_expiry === null ? "ไม่มีวันที่" : row.days_to_expiry < 0 ? `${Math.abs(row.days_to_expiry)} วันเกินกำหนด` : `อีก ${row.days_to_expiry} วัน`}</div></td>
          <td>{row.missing_documents.length ? row.missing_documents.join(", ") : row.suitability_overdue ? "Suitability หมดอายุ" : "—"}</td>
          <td>{row.action}</td>
          <td><Link className="primary-button link-button" to={`/clients/${row.client_id}?section=kyc`}>เปิดเอกสาร</Link></td>
        </tr>,
        isOpen ? <tr key={`${row.client_id}-detail`}><td colSpan={7} style={{ background: "var(--canvas)" }}><AmlDetail aml={aml} /></td></tr> : null,
      ];
    })}</tbody></table></div>}
  </div>;
}
