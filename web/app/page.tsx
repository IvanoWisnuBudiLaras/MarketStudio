"use client";

import Image from "next/image";
import { ArrowRight, ChartNoAxesColumnIncreasing, LogOut } from "lucide-react";
import { type FormEvent, type ReactNode, useEffect, useRef, useState } from "react";
import { api, ApiError, type DailyReport, type Offering, type Workspace } from "./client";
import { Panel } from "./panel";

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

export default function Home() {
  const [session, setSession] = useState<{ token: string; actor_id: string }>();
  const [ready, setReady] = useState(false);
  const [workspaces, setWorkspaces] = useState<Workspace[]>();
  const [selected, setSelected] = useState("");
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    const stored = sessionStorage.getItem("marketstudio.session");
    if (stored) setSession(JSON.parse(stored));
    setReady(true);
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
    api<{items: Workspace[]}>("workspaces", session.token).then(({ items }) => {
      if (!active) return;
      setWorkspaces(items);
      setSelected(previous => items.some(item => item.workspace_id === previous) ? previous : items[0]?.workspace_id ?? "");
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
  return <>
    <header><div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3 px-5 py-3">
      <div className="flex items-center gap-4">
        <Image className="brand" src="/marketstudio-lockup.png" width={155} height={41} alt="MarketStudio" priority />
        <span className="font-semibold">Business Studio</span>
      </div>
      {session && <button onClick={signOut}><LogOut size={16} aria-hidden />Keluar</button>}
    </div></header>
    <main className="mx-auto grid max-w-7xl gap-5 px-5 py-6 sm:py-9">
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
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div><p className="text-sm font-semibold text-blue-700">Business Studio</p><h1>{workspace?.name ?? "Ruang kerja"}</h1></div>
            {!!workspaces?.length && <label>Ruang kerja<select value={selected} onChange={event => setSelected(event.target.value)}>
              {workspaces.map(item => <option key={item.workspace_id} value={item.workspace_id}>{item.name}</option>)}
            </select></label>}
          </div>
          {error && <div><p role="alert">{error}</p><button onClick={() => setRevision(n => n + 1)}>Muat ulang ruang kerja</button></div>}
          {workspaces && <details open={workspaces.length === 0} className="panel">
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
          {workspace && <WorkspaceView key={workspace.workspace_id} workspace={workspace} token={session.token} write={write} />}
        </>
      }
    </main>
  </>;
}

function WorkspaceView({ workspace, token, write }: {
  workspace: Workspace; token: string; write: (path: string, body: object) => Promise<void>;
}) {
  const path = `workspaces/${workspace.workspace_id}`;
  const [date, setDate] = useState(() => new Intl.DateTimeFormat("sv-SE", { timeZone: workspace.timezone }).format(new Date()));
  const [offerings, setOfferings] = useState<Offering[]>([]);
  const [report, setReport] = useState<DailyReport>();
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    let active = true;
    Promise.all([
      api<{items: Offering[]}>(`${path}/offerings?status=active`, token),
      api<{report: DailyReport}>(`${path}/reports/daily?date=${encodeURIComponent(date)}`, token),
    ]).then(([catalog, daily]) => {
      if (!active) return;
      setOfferings(catalog.items);
      setReport(daily.report);
      setError("");
    }).catch(failure => {
      if (active) setError(failure instanceof ApiError ? failure.message : "Data usaha gagal dimuat.");
    });
    return () => { active = false; };
  }, [date, path, token, revision]);

  async function save(endpoint: string, body: object) {
    await write(`${path}/${endpoint}`, body);
    setRevision(n => n + 1);
  }

  const inventory = offerings.filter(offering => offering.requires_stock_movement);
  return <>
    {error && <div><p role="alert">{error}</p><button onClick={() => setRevision(n => n + 1)}>Muat ulang data usaha</button></div>}
    <div className="grid gap-5 lg:grid-cols-3">
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
    <Panel title="Laporan harian">
      <label className="mb-4 max-w-56">Tanggal ({workspace.timezone})<input type="date" required value={date} onChange={event => {
        if (event.target.value) { setReport(undefined); setDate(event.target.value); }
      }} /></label>
      {report ? <ReportView report={report} /> : !error && <p role="status">Memuat laporan…</p>}
    </Panel>
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
    ["Omzet", idr(report.revenue_idr)], ["HPP", idr(report.cogs_idr)],
    ["Laba kotor", idr(report.gross_profit_idr)], ["Margin kotor", grossMargin],
    ["Arus kas bersih", idr(report.net_cash_flow_idr)],
  ];
  return <>
    <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
      {metrics.map(([label, value]) => <div className="rounded-lg bg-blue-50 p-3" key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
    </dl>
    <p className="mt-3 text-sm text-slate-700">HPP adalah harga pokok penjualan. Arus kas bersih menghitung kas masuk dikurangi kas keluar selama periode.</p>
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
