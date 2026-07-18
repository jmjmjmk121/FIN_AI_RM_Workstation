import { Link, useSearchParams } from "react-router-dom";
import { useMemo, useState } from "react";
import { useApi, fmtTHB, fmtDate, titleCase } from "../lib/api.js";
import { Empty, ErrorNote, PageHead, Pill, Spinner, KYC_TONE, ACTIVITY_TONE } from "../components/Bits.jsx";

export default function ClientsPage() {
  const { data, error, loading } = useApi("/api/clients");
  const [params] = useSearchParams();
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState("priority");
  const view = params.get("view") || "all";
  const clients = useMemo(() => {
    let rows = [...(data?.clients || [])];
    if (query) rows = rows.filter((c) => `${c.name} ${c.client_id} ${c.goals.map((g) => g.label).join(" ")}`.toLowerCase().includes(query.toLowerCase()));
    if (view === "care") rows = rows.filter((c) => c.lane === "care");
    if (view === "inactive") rows = rows.filter((c) => ["dormant", "inactive"].includes(c.activity_status));
    if (sort === "aum") rows.sort((a, b) => b.aum - a.aum);
    if (sort === "liquidity") rows.sort((a, b) => b.investable_cash - a.investable_cash);
    if (sort === "name") rows.sort((a, b) => a.name.localeCompare(b.name));
    if (sort === "priority") rows.sort((a, b) => (a.lane === "care" ? -1 : 1) - (b.lane === "care" ? -1 : 1));
    return rows;
  }, [data, query, sort, view]);
  if (loading) return <Spinner />;
  if (error) return <ErrorNote message={error} />;
  return <div className="page-enter">
    <PageHead eyebrow="Client Record is the front door" title="ลูกค้า" lede="เริ่มจากลูกค้าและเป้าหมาย ไม่เริ่มจากผลิตภัณฑ์ ทุกแถวเชื่อมไปยังพอร์ต กิจกรรม KYC และการตัดสินใจชุดเดียวกัน" />
    <div className="toolbar card">
      <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="ค้นหาชื่อ เลขลูกค้า หรือเป้าหมาย" />
      <select value={sort} onChange={(e) => setSort(e.target.value)}><option value="priority">Care มาก่อน</option><option value="aum">AUM สูง</option><option value="liquidity">สภาพคล่องสูง</option><option value="name">ชื่อลูกค้า</option></select>
      <span className="sub-line">{clients.length} ราย · Client data: Synthetic</span>
    </div>
    {clients.length === 0 ? <Empty>ไม่พบลูกค้าในมุมมองนี้</Empty> : <div className="table-wrap"><table><thead><tr><th>ลูกค้า</th><th className="num">AUM</th><th className="num">เงินลงทุนได้</th><th>เป้าหมายหลัก</th><th>สถานะ</th><th>KYC</th><th>Why now</th><th>การทำงานต่อ</th></tr></thead><tbody>
      {clients.map((client) => <tr key={client.client_id}><td><div className="client-name">{client.name}</div><div className="sub-line">{client.client_id} · {client.segment}</div></td><td className="num">฿{fmtTHB(client.aum)}</td><td className="num">฿{fmtTHB(client.investable_cash)}</td><td><strong>{client.goals[0]?.label || "ยังไม่มี Goal Contract"}</strong><div className="sub-line">{client.goals[0] ? `${Math.round(client.goals[0].funded_ratio * 100)}% funded` : "ต้องยืนยันข้อมูล"}</div></td><td><Pill tone={ACTIVITY_TONE[client.activity_status] || "muted"}>{titleCase(client.activity_status)}</Pill><div className="sub-line">ล่าสุด {fmtDate(client.last_activity_on)}</div></td><td><Pill tone={KYC_TONE[client.kyc_status] || "muted"}>{titleCase(client.kyc_status)}</Pill></td><td style={{ maxWidth: 300 }}><strong>{client.lane === "care" ? "ควรดูแลก่อน" : "ติดตามตามหลักฐาน"}</strong><div className="sub-line">{client.why_now}</div></td><td><Link className="primary-button link-button" to={`/clients/${client.client_id}`}>เปิด Client Record</Link></td></tr>)}
    </tbody></table></div>}
  </div>;
}
