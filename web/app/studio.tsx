"use client";

import dynamic from "next/dynamic";
import Image from "next/image";
import Link from "next/link";
import { ArrowLeft, ArrowRight, ChartNoAxesColumnIncreasing, LayoutDashboard, LogOut, PanelLeftClose, PanelLeftOpen, Sheet, Sparkles } from "lucide-react";
import { type FormEvent, type ReactNode, useEffect, useRef, useState } from "react";
import { api, ApiError, type AIReviewItem, type DailyReport, type Offering, type Workspace } from "./client";
import { Panel } from "./panel";

const Worksheet = dynamic(() => import("./worksheet/editor"), { ssr: false, loading: () => <p role="status">Memuat editor…</p> });
const worksheetMedia = "(min-width: 1024px)";

const currency = new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 });
const idr = (value: number | null) => value === null ? "Belum dinilai" : currency.format(value);

function Form({ label, onSubmit, children }: {
  label: string;
  onSubmit: (data: FormData) => Promise<void>;
  children: ReactNode;
}) {
  const running = useRef(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (running.current) return;
    running.current = true;
    setBusy(true);
    setError("");
    setMessage("");
    const form = event.currentTarget;
    try {
      await onSubmit(new FormData(form));
      form.reset();
      setMessage("Tersimpan.");
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : "Koneksi terputus. Coba kembali dengan data yang sama.");
    } finally {
      running.current = false;
      setBusy(false);
    }
  }

  return <form className="grid gap-3" onSubmit={submit}>
    <fieldset className="grid gap-3" disabled={busy}>{children}
      <button className="justify-self-start" disabled={busy}>{busy ? "Memproses…" : label}<ArrowRight size={16} aria-hidden /></button>
    </fieldset>
    {error && <p role="alert">{error}</p>}
    {message && <p role="status">{message}</p>}
  </form>;
}

function Field({ label, name, type = "text", step, min }: {
  label: string; name: string; type?: string; step?: string; min?: string;
}) {
  return <label>{label}<input name={name} type={type} step={step} min={min} required /></label>;
}

function text(data: FormData, field: string) { return String(data.get(field) ?? ""); }

export default function Studio({ destination }: { destination: "business" | "worksheet" }) {
  const [session, setSession] = useState<{ token: string; actor_id: string }>();
  const [ready, setReady] = useState(false);
  const [workspaces, setWorkspaces] = useState<Workspace[]>();
  const [selected, setSelected] = useState("");
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const [collapsed, setCollapsed] = useState(false);
  const [worksheetAvailable, setWorksheetAvailable] = useState(false);
  const isWorksheet = destination === "worksheet";

  useEffect(() => {
    const stored = sessionStorage.getItem("marketstudio.session");
    if (stored) setSession(JSON.parse(stored));
    setCollapsed(sessionStorage.getItem("marketstudio.sidebar") === "collapsed");
    const media = window.matchMedia(worksheetMedia);
    const update = () => setWorksheetAvailable(media.matches);
    update();
    media.addEventListener("change", update);
    setReady(true);
    return () => media.removeEventListener("change", update);
  }, []);

  function signOut() {
    sessionStorage.removeItem("marketstudio.session");
    setSession(undefined);
    setWorkspaces(undefined);
    setSelected("");
    setError("");
  }

  useEffect(() => {
    if (!session) return;
    let active = true;
    const preference = `marketstudio.workspace:${session.actor_id}`;
    api<{items: Workspace[]}>("workspaces", session.token).then(({ items }) => {
      if (!active) return;
      setWorkspaces(items);
      const previous = sessionStorage.getItem(preference);
      setSelected(items.find(item => item.workspace_id === previous)?.workspace_id ?? items[0]?.workspace_id ?? "");
      setError("");
    }).catch(failure => {
      if (!active) return;
      if (failure instanceof ApiError && failure.status === 401) signOut();
      setError(failure instanceof ApiError ? failure.message : "Ruang kerja gagal dimuat.");
    });
    return () => { active = false; };
  }, [session, revision]);

  async function write(path: string, body: object) {
    if (!session) return;
    const scope = `marketstudio.pending:${session.actor_id}:${path}`;
    const serialized = JSON.stringify(body);
    const previous = sessionStorage.getItem(scope);
    const pending = previous ? JSON.parse(previous) as { serialized: string; key: string } : undefined;
    if (pending && pending.serialized !== serialized) {
      throw new ApiError(409, "Hasil permintaan sebelumnya belum diketahui. Kirim ulang data sebelumnya untuk memeriksa hasilnya.");
    }
    const key = pending?.key ?? crypto.randomUUID();
    sessionStorage.setItem(scope, JSON.stringify({ serialized, key }));
    try {
      await api(path, session.token, body, key);
      sessionStorage.removeItem(scope);
    } catch (failure) {
      if (failure instanceof ApiError && failure.status < 500 && failure.status !== 401 && failure.status !== 403) {
        sessionStorage.removeItem(scope);
      }
      throw failure;
    }
  }

  const workspace = workspaces?.find(item => item.workspace_id === selected);
  const studioName = isWorksheet ? "Lembar kerja" : "Business Studio";
  return <div className="app-shell" data-collapsed={collapsed}>
    <a className="skip-link" href="#konten">Lewati ke konten</a>
    <aside className="sidebar">
      <div className="sidebar-brand">
        <Image src="/marketstudio-mark.png" width={36} height={36} alt="" priority />
        <span className="sidebar-label">MarketStudio</span>
      </div>
      {session && <nav aria-label="Navigasi studio">
        <Link href="/" aria-label="Business Studio" aria-current={!isWorksheet ? "page" : undefined} title="Business Studio">
          <LayoutDashboard size={20} aria-hidden /><span className="sidebar-label">Business Studio</span>
        </Link>
        {worksheetAvailable && <Link href="/worksheet" aria-label="Lembar kerja" aria-current={isWorksheet ? "page" : undefined} title="Lembar kerja">
          <Sheet size={20} aria-hidden /><span className="sidebar-label">Lembar kerja</span>
        </Link>}
      </nav>}
      <button type="button" className="sidebar-toggle" aria-label={collapsed ? "Perluas sidebar" : "Ringkas sidebar"}
        aria-expanded={!collapsed} onClick={() => {
          sessionStorage.setItem("marketstudio.sidebar", collapsed ? "expanded" : "collapsed");
          setCollapsed(!collapsed);
        }}>
        {collapsed ? <PanelLeftOpen size={20} aria-hidden /> : <PanelLeftClose size={20} aria-hidden />}
        <span className="sidebar-label">Ringkas sidebar</span>
      </button>
    </aside>
    <div className="app-content">
      <header className="topbar">
        <span className="topbar-title">{session ? studioName : "MarketStudio"}</span>
        {session && <div className="topbar-actions">
          {!!workspaces?.length && <label className="workspace-selector">
            <span className="sr-only">Ruang kerja</span>
            <select value={selected} onChange={event => {
              setSelected(event.target.value);
              sessionStorage.setItem(`marketstudio.workspace:${session.actor_id}`, event.target.value);
            }}>
              {workspaces.map(item => <option key={item.workspace_id} value={item.workspace_id}>{item.name}</option>)}
            </select>
          </label>}
          <button className="sign-out" onClick={signOut}><LogOut size={17} aria-hidden />Keluar</button>
        </div>}
      </header>
      <main id="konten" tabIndex={-1} className="studio-main">
      {!ready ? <p role="status">Memuat sesi…</p> : !session ?
        <div className="max-w-md"><Panel title="Masuk ke ruang kerja">
          <Form label="Masuk" onSubmit={async data => {
            const { item } = await api<{item: {token: string; actor_id: string}}>(
              "sessions", "", { actor_id: text(data, "actor"), passcode: text(data, "passcode") },
            );
            sessionStorage.setItem("marketstudio.session", JSON.stringify(item));
            setSession(item);
          }}>
            <Field label="Identitas" name="actor" />
            <Field label="Kode akses" name="passcode" type="password" />
          </Form>
          {error && <p role="alert">{error}</p>}
        </Panel></div> :
        <>
          <div className="studio-heading">
            <h1>{isWorksheet ? "Lembar kerja perencanaan" : workspace?.name ?? "Ruang kerja"}</h1>
            {!isWorksheet && workspace && <a className="primary-link" href="#transaksi">Catat transaksi <ArrowRight size={16} aria-hidden /></a>}
          </div>
          {error && <div><p role="alert">{error}</p><button onClick={() => setRevision(n => n + 1)}>Muat ulang ruang kerja</button></div>}
          {!isWorksheet && workspaces && <details open={workspaces.length === 0} className="panel">
            <summary className="cursor-pointer font-semibold">Buat profil usaha</summary>
            <div className="mt-3 max-w-md"><Form label="Buat ruang kerja" onSubmit={async data => {
              await write("workspaces", { name: text(data, "name"), business_type: text(data, "type"), timezone: "Asia/Jakarta" });
              setRevision(n => n + 1);
            }}>
              <Field label="Nama usaha" name="name" />
              <label>Jenis usaha<select name="type"><option value="umkm_goods">Perdagangan barang</option>
                <option value="umkm_service">Jasa</option><option value="umkm_hybrid">Barang dan jasa</option></select></label>
            </Form></div>
          </details>}
          {isWorksheet && (!worksheetAvailable || workspaces?.length === 0) ?
            <Panel title={worksheetAvailable ? "Siapkan ruang kerja" : "Gunakan layar yang lebih lebar"}>
              <p className="mb-3">{worksheetAvailable ? "Buat profil usaha di Business Studio untuk memakai lembar kerja." : "Editor lembar kerja tersedia pada layar dengan lebar minimal 1024 piksel."}</p>
              <Link className="text-link" href="/"><ArrowLeft size={16} aria-hidden />Kembali ke Business Studio</Link>
            </Panel> :
            workspace && <WorkspaceView key={workspace.workspace_id} workspace={workspace} token={session.token} write={write} isWorksheet={isWorksheet} />}
        </>
      }
      </main>
    </div>
  </div>;
}

function WorkspaceView({ workspace, token, write, isWorksheet }: {
  workspace: Workspace; token: string; write: (path: string, body: object) => Promise<void>; isWorksheet: boolean;
}) {
  const path = `workspaces/${workspace.workspace_id}`;
  const [date, setDate] = useState(() => new Intl.DateTimeFormat("sv-SE", { timeZone: workspace.timezone }).format(new Date()));
  const [offerings, setOfferings] = useState<Offering[]>([]);
  const [report, setReport] = useState<DailyReport>();
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const [aiReview, setAiReview] = useState<AIReviewItem>();
  const [loadingReview, setLoadingReview] = useState(false);
  const [reviewError, setReviewError] = useState("");

  useEffect(() => {
    let active = true;
    setAiReview(undefined);
    setReviewError("");
    Promise.all([
      isWorksheet ? undefined : api<{items: Offering[]}>(`${path}/offerings?status=active`, token),
      api<{report: DailyReport}>(`${path}/reports/daily?date=${encodeURIComponent(date)}`, token),
    ]).then(([catalog, daily]) => {
      if (!active) return;
      if (catalog) setOfferings(catalog.items);
      setReport(daily.report);
      setError("");
    }).catch(failure => {
      if (active) setError(failure instanceof ApiError ? failure.message : "Data usaha gagal dimuat.");
    });
    return () => { active = false; };
  }, [date, path, token, revision, isWorksheet]);

  async function runAiReview() {
    setLoadingReview(true);
    setReviewError("");
    try {
      const { item } = await api<{ item: AIReviewItem }>(
        `${path}/reports/daily/ai-review`,
        token,
        { date }
      );
      setAiReview(item);
    } catch (failure) {
      setReviewError(failure instanceof ApiError ? failure.message : "AI Review gagal dijalankan.");
    } finally {
      setLoadingReview(false);
    }
  }

  async function save(endpoint: string, body: object) {
    await write(`${path}/${endpoint}`, body);
    setRevision(n => n + 1);
  }

  const inventory = offerings.filter(offering => offering.requires_stock_movement);
  return <>
    {error && <div><p role="alert">{error}</p><button onClick={() => setRevision(n => n + 1)}>Muat ulang data usaha</button></div>}
    {isWorksheet ? <Panel title={workspace.name}>
      {report && !error && <p className="mb-3" aria-label="Referensi laporan">
        Omzet {idr(report.revenue_idr)} · {report.period.date} ({report.period.timezone}) · Laporan harian
      </p>}
      <Worksheet path={`${path}/worksheet`} token={token} />
    </Panel> : <>
    <Panel title="Laporan harian">
      <label className="mb-4 max-w-56">Tanggal ({workspace.timezone})<input type="date" required value={date} onChange={event => {
        if (event.target.value) { setReport(undefined); setDate(event.target.value); }
      }} /></label>
      {report ? <ReportView report={report} /> : !error && <p role="status">Memuat laporan…</p>}
    </Panel>
    <AIReviewPanel
      review={aiReview}
      loading={loadingReview}
      error={reviewError}
      onRun={runAiReview}
      disabled={!report}
    />
    <div id="transaksi" tabIndex={-1} className="transaction-grid">
      <Panel title="Tambah produk">
        <Form label="Simpan produk" onSubmit={data => save("offerings", {
          name: text(data, "name"), offering_type: "goods", unit: text(data, "unit"), unit_price_idr: Number(data.get("price")),
        })}>
          <Field label="Nama produk" name="name" /><Field label="Satuan" name="unit" />
          <Field label="Harga jual per satuan (Rp)" name="price" type="number" min="0" step="1" />
        </Form>
      </Panel>
      {inventory.length > 0 && <Panel title="Pembelian tunai">
        <TransactionForm kind="purchases" offerings={inventory} save={save} />
      </Panel>}
      {offerings.length > 0 && <Panel title="Penjualan tunai">
        <TransactionForm kind="sales" offerings={offerings} save={save} />
      </Panel>}
    </div>
    <Panel title="Katalog usaha">
      {!offerings.length ? <p>Belum ada produk.</p> : <div className="overflow-x-auto"><table className="w-full">
        <thead><tr><th>Produk</th><th>Harga jual per satuan</th><th>Biaya satuan WA</th></tr></thead>
        <tbody>{offerings.map(offering => <tr key={offering.offering_id}><td>{offering.name}</td>
          <td>{idr(offering.unit_price_idr)}/{offering.unit}</td>
          <td>{idr(offering.unit_cost_idr)}{offering.unit_cost_idr !== null && `/${offering.unit}`}</td>
        </tr>)}</tbody>
      </table></div>}
    </Panel>
    </>}
  </>;
}

function TransactionForm({ kind, offerings, save }: {
  kind: "purchases" | "sales";
  offerings: Offering[];
  save: (endpoint: string, body: object) => Promise<void>;
}) {
  const purchase = kind === "purchases";
  return <Form label={purchase ? "Catat pembelian" : "Catat penjualan"} onSubmit={data => {
    const item = { offering_id: text(data, "product"), qty: text(data, "qty") };
    const amount = Number(data.get("amount"));
    return save(kind, purchase ?
      { ...item, payment_method: "cash", total_cost_idr: amount } :
      { lines: [{ ...item, total_price_idr: amount }], payment_method: "cash" });
  }}>
    <label>Produk<select name="product">{offerings.map(item => <option key={item.offering_id} value={item.offering_id}>{item.name} ({item.unit})</option>)}</select></label>
    <Field label="Jumlah" name="qty" type="number" min="0" step="any" />
    <Field label={purchase ? "Total biaya (Rp)" : "Total penjualan (Rp)"} name="amount" type="number" min="0" step="1" />
  </Form>;
}

function ReportView({ report }: { report: DailyReport }) {
  const grossMargin = report.gross_profit_idr !== null && report.revenue_idr > 0
    ? new Intl.NumberFormat("id-ID", { style: "percent", maximumFractionDigits: 2 }).format(report.gross_profit_idr / report.revenue_idr)
    : "—";
  const metrics = [
    ["Omzet", idr(report.revenue_idr)], ["Laba kotor", idr(report.gross_profit_idr)],
    ["Arus kas bersih", idr(report.net_cash_flow_idr)], ["Nilai stok akhir", idr(report.ending_inventory.total_value_idr)],
  ];
  return <>
    <dl className="report-metrics">
      {metrics.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
    </dl>
    <dl className="mt-4 grid grid-cols-2 gap-4 sm:grid-cols-4">
      {[
        ["HPP", idr(report.cogs_idr)], ["Margin kotor", grossMargin],
        ["Kas masuk", idr(report.cash_in_idr)], ["Kas keluar", idr(report.cash_out_idr)],
      ].map(([label, value]) => <div key={label}><dt>{label}</dt><dd className="text-base">{value}</dd></div>)}
    </dl>
    <p className="mt-3 text-sm text-slate-700">HPP adalah harga pokok penjualan.</p>
    <div className="mt-5 grid gap-5 sm:grid-cols-2">
      <div><h3 className="mb-2 flex items-center gap-2 font-semibold"><ChartNoAxesColumnIncreasing size={17} aria-hidden />Stok akhir</h3>
        {report.ending_inventory.items.length ? <ul>{report.ending_inventory.items.map(item =>
          <li key={item.offering_id}>{item.name} · {Number(item.qty_remaining).toLocaleString("id-ID")} {item.unit} · {idr(item.value_idr)}</li>,
        )}</ul> : <p>Belum ada pergerakan stok.</p>}
      </div>
      <div><h3 className="mb-2 font-semibold">Transaksi periode ini</h3>
        <p>{report.drill_down.purchases.length} pembelian · {report.drill_down.sales.length} penjualan</p>
      </div>
    </div>
  </>;
}

function AIReviewPanel({
  review,
  loading,
  error,
  onRun,
  disabled,
}: {
  review?: AIReviewItem;
  loading: boolean;
  error: string;
  onRun: () => void;
  disabled: boolean;
}) {
  return (
    <Panel title="AI Business Review">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <p className="text-sm text-slate-700 max-w-xl">
          Analisis otomatis terhadap snapshot laporan harian aktif dengan verifikasi rujukan angka riil.
        </p>
        <button
          type="button"
          onClick={onRun}
          disabled={disabled || loading}
          aria-busy={loading}
          className="review-action-btn"
        >
          <Sparkles size={16} aria-hidden />
          {loading ? "Menganalisis laporan…" : review ? "Perbarui AI Review" : "Jalankan AI Review"}
        </button>
      </div>

      {loading && <p role="status" className="text-slate-600">Menghubungkan analisis AI ke snapshot laporan…</p>}
      {error && <p role="alert">{error}</p>}

      {!loading && !error && !review && (
        <p className="text-slate-600 text-sm">
          Klik &quot;Jalankan AI Review&quot; untuk menganalisis metrik omzet, HPP, arus kas, dan stok akhir periode ini dengan rujukan angka riil.
        </p>
      )}

      {!loading && review && (
        <article className="ai-review-content grid gap-4" aria-label="Hasil AI Business Review">
          <div className="flex flex-wrap items-center gap-2">
            <span
              className={`provenance-badge ${
                review.provider_mode === "live_provider"
                  ? "live"
                  : review.provider_mode === "stub_test"
                  ? "stub"
                  : "fallback"
              }`}
            >
              {review.provider_mode === "live_provider"
                ? `AI Terhubung (${review.config_status.provider ?? "9Router"}: ${review.config_status.model ?? "ag/gemini-3.8-flash"})`
                : review.provider_mode === "stub_test"
                ? "Simulasi AI (Stub Test)"
                : `Fallback Deterministik (Lokal${review.fallback_reason ? `: ${review.fallback_reason}` : ""})`}
            </span>
            {review.status === "fallback" && (
              <span className="fallback-note text-xs text-amber-800 bg-amber-50 border border-amber-200 px-2 py-0.5 rounded">
                Mode fallback aktif: interpretasi berbasis fakta lokal.
              </span>
            )}
          </div>

          <div className="review-summary">
            <h3 className="font-semibold text-base mb-1">Ringkasan Analisis</h3>
            <p className="leading-relaxed">{review.review.summary}</p>
          </div>

          {review.review.highlights.length > 0 && (
            <div className="review-highlights">
              <h3 className="font-semibold text-base mb-1">Temuan Kunci</h3>
              <ul className="list-disc pl-5 space-y-1">
                {review.review.highlights.map((h, i) => (
                  <li key={i}>{h}</li>
                ))}
              </ul>
            </div>
          )}

          {review.review.missing_data.length > 0 && (
            <div className="review-limitations text-sm text-slate-700 bg-slate-50 border border-slate-200 rounded p-3">
              <h4 className="font-semibold text-slate-800 mb-1">Catatan Data &amp; Batasan:</h4>
              <ul className="list-disc pl-5 space-y-0.5">
                {review.review.missing_data.map((m, i) => (
                  <li key={i}>{m}</li>
                ))}
              </ul>
            </div>
          )}

          <div className="review-citations text-xs text-slate-600 border-t border-slate-200 pt-3">
            <div className="flex flex-wrap gap-x-4 gap-y-1">
              <span>
                Rujukan snapshot: <code>{review.review.citations.snapshot_id}</code>
              </span>
              <span>Periode: {review.review.citations.period_date}</span>
              <span>{review.review.citations.source_ids.length} transaksi diverifikasi</span>
            </div>
            <p className="mt-1.5 italic text-slate-500">
              AI Review bersifat read-only dan tidak mengubah transaksi atau pembukuan keuangan.
            </p>
          </div>
        </article>
      )}
    </Panel>
  );
}
