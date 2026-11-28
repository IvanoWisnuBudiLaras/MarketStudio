"use client";

import { useEffect, useRef, useState } from "react";
import { createUniver, LocaleType, type ICellData, type IWorkbookData } from "@univerjs/presets";
import { UniverSheetsCorePreset } from "@univerjs/preset-sheets-core";
import enUS from "@univerjs/preset-sheets-core/locales/en-US";
import "@univerjs/preset-sheets-core/lib/index.css";
import { api, ApiError } from "./client";

type Cells = Record<string, Record<string, Pick<ICellData, "v" | "t" | "f">>>;
type Document = { cells: Cells; revision: number; can_edit: boolean };
const sheetId = "planning";

export default function Worksheet({ path, token }: { path: string; token: string }) {
  const host = useRef<HTMLDivElement>(null);
  const snapshot = useRef<() => Promise<IWorkbookData>>(null);
  const revision = useRef(0);
  const saving = useRef(false);
  const [attempt, setAttempt] = useState(0);
  const [ready, setReady] = useState(false);
  const [canEdit, setCanEdit] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    let dispose: (() => void) | undefined;
    const container = document.createElement("div");
    container.style.height = "100%";
    host.current!.append(container);
    api<{ item: Document }>(path, token).then(({ item }) => {
      if (!active) return;
      const { univer, univerAPI } = createUniver({
        locale: LocaleType.EN_US,
        locales: { [LocaleType.EN_US]: enUS },
        presets: [UniverSheetsCorePreset({
          container, header: false, toolbar: false, footer: false, contextMenu: false, disableAutoFocus: true,
        })],
      });
      dispose = () => univer.dispose();
      const workbook = univerAPI.createWorkbook({
        id: "marketstudio-worksheet", name: "Perencanaan",
        sheetOrder: [sheetId],
        sheets: { [sheetId]: { id: sheetId, name: "Perencanaan", rowCount: 100, columnCount: 26, cellData: item.cells } },
      });
      workbook.setEditable(item.can_edit);
      snapshot.current = async () => {
        if (workbook.isCellEditing() && !await workbook.endEditingAsync()) {
          throw new Error("Active cell edit could not be committed.");
        }
        return workbook.save();
      };
      revision.current = item.revision;
      setCanEdit(item.can_edit);
      setReady(true);
    }).catch(failure => {
      if (active) setError(failure instanceof ApiError ? failure.message : "Lembar kerja gagal dimuat.");
    });
    return () => {
      active = false;
      snapshot.current = null;
      queueMicrotask(() => {
        dispose?.();
        container.remove();
      });
    };
  }, [path, token, attempt]);

  async function save() {
    if (saving.current || !snapshot.current) return;
    saving.current = true;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const cells: Cells = {};
      const source = (await snapshot.current()).sheets[sheetId].cellData ?? {};
      for (const row of Object.keys(source)) {
        const columns = source[Number(row)];
        for (const column of Object.keys(columns)) {
          const cell = columns[Number(column)];
          if (cell.f != null) (cells[row] ??= {})[column] = { f: cell.f };
          else if (cell.v != null) (cells[row] ??= {})[column] = { v: cell.v, t: cell.t ?? undefined };
        }
      }
      const { item } = await api<{ item: { revision: number } }>(path, token, { cells, revision: revision.current }, undefined, "PUT");
      revision.current = item.revision;
      setMessage("Lembar kerja tersimpan.");
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : "Penyimpanan gagal. Coba simpan kembali.");
    } finally {
      saving.current = false;
      setBusy(false);
    }
  }

  return <>
    <p className="mb-3">Simpan nilai dan rumus sel untuk perencanaan. Angka laporan di atas berasal dari transaksi ruang kerja.</p>
    {!ready && !error && <p role="status">Memuat lembar kerja…</p>}
    <div className="worksheet-editor relative h-[420px] min-w-0 overflow-hidden rounded-lg border border-slate-200"
      aria-label="Editor lembar kerja" ref={host} />
    {ready && canEdit && <button className="mt-3" disabled={busy} onClick={save}>Simpan lembar kerja</button>}
    {ready && !canEdit && <p>Baca saja.</p>}
    {message && <p role="status">{message}</p>}
    {error && <p role="alert">{error}</p>}
    {!ready && error && <button onClick={() => { setError(""); setAttempt(n => n + 1); }}>Muat ulang lembar kerja</button>}
  </>;
}
