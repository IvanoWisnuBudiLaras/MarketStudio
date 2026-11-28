import { spawn, execFileSync, type ChildProcess } from "node:child_process";
import { randomBytes } from "node:crypto";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { expect, test, type Page } from "@playwright/test";

const root = resolve(process.cwd(), "..");
const python = process.env.MARKETSTUDIO_TEST_PYTHON ?? join(root, ".venv/bin/python");
const sql = (db: string, statement: string) => execFileSync(python, [
  "-c", "import sqlite3,sys; conn=sqlite3.connect(sys.argv[1]); print(conn.execute(sys.argv[2]).fetchall()); conn.commit()", db, statement,
], { encoding: "utf8" }).trim();

function freePort() {
  return new Promise<number>((resolve, reject) => {
    const socket = createServer().once("error", reject).listen(0, "127.0.0.1", () => {
      const address = socket.address();
      if (!address || typeof address === "string") throw new Error("Missing test port");
      socket.close(error => error ? reject(error) : resolve(address.port));
    });
  });
}

async function stop(child: ChildProcess) {
  if (child.exitCode !== null || child.signalCode !== null) return;
  await new Promise<void>(resolve => {
    child.once("exit", () => resolve());
    child.kill("SIGTERM");
  });
}

async function login(page: Page, actor: string, secret: string) {
  await page.getByLabel("Identitas").fill(actor);
  await page.getByLabel("Kode akses").fill(secret);
  await page.getByRole("button", { name: "Masuk", exact: true }).click();
  await expect(page.getByRole("button", { name: "Keluar" })).toBeVisible();
}

test("schema-only business journey, replay, rollback, restart and tenant isolation", async ({ page, browser }, testInfo) => {
  const dir = mkdtempSync(join(tmpdir(), "ms-browser-"));
  const db = join(dir, "business.sqlite3");
  const identities = join(dir, "identities.json");
  const owner = randomBytes(32).toString("hex");
  const outsider = randomBytes(32).toString("hex");
  writeFileSync(identities, JSON.stringify({ "owner-test": owner, "outsider-test": outsider }), { mode: 0o600 });

  const webPort = await freePort();
  const apiPort = await freePort();
  const env = {
    ...process.env, MARKETSTUDIO_ENV: "test", MARKETSTUDIO_V3_SQLITE: db,
    MARKETSTUDIO_V3_IDENTITIES: identities, MARKETSTUDIO_V3_API_PORT: String(apiPort),
  };
  const origin = `http://127.0.0.1:${webPort}`;
  const upstream = `http://127.0.0.1:${apiPort}`;
  let backend: ChildProcess;
  const errors: string[] = [];
  const startBackend = async () => {
    backend = spawn(python, ["-m", "uvicorn", "app.v3:app", "--host", "127.0.0.1", "--port", String(apiPort)], {
      cwd: root, env, stdio: ["ignore", "inherit", "inherit"],
    });
    await expect.poll(async () => (await fetch(`${upstream}/health`).catch(() => undefined))?.status).toBe(200);
  };
  const web = spawn(process.execPath, ["node_modules/next/dist/bin/next", "start", "--hostname", "127.0.0.1", "--port", String(webPort)], {
    env, stdio: "inherit",
  });
  try {
    await startBackend();
    for (const table of ["workspaces", "offerings", "purchases", "sales", "sessions"]) {
      expect(sql(db, `SELECT COUNT(*) FROM ${table}`)).toBe("[(0,)]");
    }
    await expect.poll(async () => (await fetch(origin).catch(() => undefined))?.status).toBe(200);
    page.on("pageerror", error => errors.push(error.message));
    await page.goto(origin);
    await login(page, "owner-test", owner);
    await expect(page.getByRole("heading", { name: "Ruang kerja", exact: true })).toBeVisible();
    await page.screenshot({ path: testInfo.outputPath("business-empty-1440.png"), fullPage: true });
    await page.getByLabel("Nama usaha").fill("Warung Padi");
    await page.getByRole("button", { name: "Buat ruang kerja" }).click();
    await expect(page.getByRole("heading", { name: "Warung Padi" })).toBeVisible();
    const worksheetCanvas = page.getByLabel("Editor lembar kerja").locator("canvas:visible").first();
    const openWorksheet = async () => {
      await page.getByRole("link", { name: "Lembar kerja", exact: true }).click();
      await expect(page).toHaveURL(`${origin}/worksheet`);
      await expect(page.getByRole("button", { name: "Simpan lembar kerja" })).toBeVisible();
      await expect(worksheetCanvas).toBeVisible();
    };
    await openWorksheet();
    await expect(page.getByLabel("Referensi laporan")).toHaveText(/Omzet Rp\s?0 ·/);
    expect(sql(db, "SELECT COUNT(*) FROM v3_worksheets")).toBe("[(0,)]");
    const openBusiness = async () => {
      await page.getByRole("link", { name: "Business Studio", exact: true }).click();
      await expect(page).toHaveURL(`${origin}/`);
    };
    await openBusiness();
    await page.getByLabel("Nama produk").fill("Beras medium");
    await page.getByLabel("Satuan", { exact: true }).fill("kg");
    await page.getByLabel("Harga jual per satuan (Rp)").fill("14500");
    await page.getByRole("button", { name: "Simpan produk" }).click();

    const purchase = page.getByRole("heading", { name: "Pembelian tunai" }).locator("..");
    await purchase.getByLabel("Jumlah").fill("10");
    await purchase.getByLabel("Total biaya (Rp)").fill("120000");
    await purchase.getByRole("button", { name: "Catat pembelian" }).click();
    await expect(page.getByText(/Rp\s?12\.000\/kg/)).toBeVisible();

    const sale = page.getByRole("heading", { name: "Penjualan tunai" }).locator("..");
    await sale.getByLabel("Jumlah").fill("0");
    await sale.getByLabel("Total penjualan (Rp)").fill("29000");
    await sale.getByRole("button", { name: "Catat penjualan" }).click();
    await expect(sale.getByRole("alert")).toContainText("Data penjualan tidak valid");
    await expect(sale.getByLabel("Total penjualan (Rp)")).toHaveValue("29000");
    expect(sql(db, "SELECT COUNT(*) FROM sales")).toBe("[(0,)]");

    await sale.getByLabel("Jumlah").fill("2");
    sql(db, "CREATE TRIGGER reject_test_sale BEFORE INSERT ON cash_movements WHEN NEW.direction = 'in' BEGIN SELECT RAISE(ABORT,'rollback-test'); END");
    const button = sale.getByRole("button", { name: "Catat penjualan" });
    await button.click();
    await expect(sale.getByRole("alert")).toContainText("Operasi gagal");
    expect(sql(db, "SELECT COUNT(*) FROM sales")).toBe("[(0,)]");
    expect(sql(db, "SELECT COUNT(*) FROM stock_movements")).toBe("[(1,)]");
    expect(sql(db, "SELECT COUNT(*) FROM cash_movements")).toBe("[(1,)]");
    sql(db, "DROP TRIGGER reject_test_sale");

    const keys: (string | undefined)[] = [];
    await page.route("**/sales", async route => {
      keys.push(route.request().headers()["idempotency-key"]);
      if (keys.length === 1) {
        expect((await route.fetch()).status()).toBe(201);
        await route.abort();
      } else {
        await route.continue();
      }
    });
    await button.evaluate((element: HTMLButtonElement) => {
      element.form!.requestSubmit(element);
      element.form!.requestSubmit(element);
    });
    await expect(sale.getByRole("alert")).toContainText("Koneksi terputus");
    await expect(sale.getByLabel("Jumlah")).toHaveValue("2");
    await button.click();
    await expect(sale.getByRole("status")).toHaveText("Tersimpan.");
    expect(keys).toHaveLength(2);
    expect(keys[0]).toBeTruthy();
    expect(keys[0]).toBe(keys[1]);

    const values = async () => {
      const report = page.getByRole("heading", { name: "Laporan harian" }).locator("..");
      for (const [label, value] of [
        ["Omzet", /Rp\s?29\.000/], ["HPP", /Rp\s?24\.000/], ["Laba kotor", /Rp\s?5\.000/],
        ["Margin kotor", /17,24\s?%/], ["Arus kas bersih", /-\s?Rp\s?91\.000/],
        ["Nilai stok akhir", /Rp\s?96\.000/], ["Kas masuk", /Rp\s?29\.000/], ["Kas keluar", /Rp\s?120\.000/],
      ] as const) {
        await expect(report.getByText(label, { exact: true }).locator("..").locator("dd")).toHaveText(value);
      }
      await expect(report.getByText(/Beras medium · 8 kg · Rp\s?96\.000/)).toBeVisible();
      await expect(report.getByText("1 pembelian · 1 penjualan")).toBeVisible();
      await expect(page.getByText(/Rp\s?12\.000\/kg/)).toBeVisible();
    };
    await values();
    expect(sql(db, "SELECT total_revenue_idr,total_cogs_idr FROM sales")).toBe("[(29000, 24000)]");
    expect(sql(db, "SELECT amount_idr FROM cash_movements ORDER BY direction")).toBe("[(29000,), (120000,)]");

    const aiReviewPanel = page.getByRole("heading", { name: "AI Business Review" }).locator("..");
    await expect(aiReviewPanel.getByRole("button", { name: "Jalankan AI Review" })).toBeVisible();
    await aiReviewPanel.getByRole("button", { name: "Jalankan AI Review" }).click();
    await expect(aiReviewPanel.getByLabel("Hasil AI Business Review")).toBeVisible();
    await expect(aiReviewPanel.getByText("Ringkasan Analisis")).toBeVisible();
    await expect(aiReviewPanel.getByText(/Omzet Rp\s?29[,.]000/)).toBeVisible();
    await expect(aiReviewPanel.getByText(/Fallback Deterministik|AI Terhubung/)).toBeVisible();
    await expect(aiReviewPanel.getByText(/read-only dan tidak mengubah transaksi/)).toBeVisible();
    const aiScreenshot = testInfo.outputPath("business-ai-review-1440.png");
    await page.screenshot({ path: aiScreenshot, fullPage: true });
    await testInfo.attach("Hasil AI Business Review", { path: aiScreenshot, contentType: "image/png" });

    const ledger = () => ["sales", "purchases", "cash_movements", "stock_movements"]
      .map(table => sql(db, `SELECT * FROM ${table} ORDER BY rowid`));
    const before = ledger();
    const reference = /Omzet Rp\s?29\.000 · \d{4}-\d{2}-\d{2} \(Asia\/Jakarta\) · Laporan harian/;
    await openWorksheet();
    await expect(page.getByLabel("Referensi laporan")).toHaveText(reference);
    await worksheetCanvas.dblclick({ position: { x: 64, y: 30 } });
    await page.keyboard.insertText("Target stok 12 kg");
    await page.getByRole("button", { name: "Simpan lembar kerja" }).click();
    await expect(page.getByText("Lembar kerja tersimpan.")).toBeVisible();
    expect(sql(db, "SELECT cells_json FROM v3_worksheets")).toContain("Target stok 12 kg");

    await page.reload();
    await expect(page).toHaveURL(`${origin}/worksheet`);
    await expect(page.getByLabel("Referensi laporan")).toHaveText(reference);
    await page.context().grantPermissions(["clipboard-read", "clipboard-write"]);
    await worksheetCanvas.click({ position: { x: 64, y: 30 } });
    await page.keyboard.press("Control+c");
    await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toBe("Target stok 12 kg");
    const worksheetScreenshot = testInfo.outputPath("univer-worksheet.png");
    await page.screenshot({ path: worksheetScreenshot, fullPage: true });
    await testInfo.attach("Lembar kerja Univer", { path: worksheetScreenshot, contentType: "image/png" });
    expect(ledger()).toEqual(before);
    const selector = page.getByRole("combobox", { name: "Ruang kerja", exact: true });
    const workspace = await selector.inputValue();
    await openBusiness();
    await page.getByText("Buat profil usaha", { exact: true }).click();
    const secondName = page.getByLabel("Nama usaha");
    await secondName.fill("Warung Sari");
    await page.getByRole("button", { name: "Buat ruang kerja" }).click();
    await expect(selector.getByRole("option", { name: "Warung Sari" })).toHaveCount(1);
    await selector.selectOption({ label: "Warung Sari" });
    await expect(page.getByRole("heading", { name: "Warung Sari" })).toBeVisible();
    await expect(page.getByText("Belum ada produk.")).toBeVisible();
    const second = await selector.inputValue();
    await openWorksheet();
    await expect(selector).toHaveValue(second);
    await expect(page.getByLabel("Referensi laporan")).toHaveText(/Omzet Rp\s?0 ·/);
    await worksheetCanvas.click({ position: { x: 64, y: 30 } });
    await page.keyboard.press("Control+c");
    await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toBe("");
    await selector.selectOption(workspace);
    await expect(page.getByLabel("Referensi laporan")).toHaveText(reference);
    await openBusiness();
    await expect(selector).toHaveValue(workspace);
    await page.reload();
    await values();
    await page.getByRole("button", { name: "Keluar" }).click();
    await stop(backend!);
    await startBackend();
    await login(page, "owner-test", owner);
    await values();
    await expect(page.locator(".astryx-card.business-panel").first()).toHaveCSS("border-radius", "14px");
    await page.keyboard.press("Tab");
    await page.getByRole("button", { name: "Ringkas sidebar" }).focus();
    await expect(page.getByRole("button", { name: "Ringkas sidebar" })).toHaveCSS("outline-style", "solid");
    await page.keyboard.press("Enter");
    await expect(page.getByRole("button", { name: "Perluas sidebar" })).toHaveAttribute("aria-expanded", "false");
    await openWorksheet();
    await expect(page.getByRole("button", { name: "Perluas sidebar" })).toBeVisible();
    await openBusiness();
    await page.getByRole("button", { name: "Perluas sidebar" }).click();

    for (const width of [1440, 1280, 768, 390]) {
      await page.setViewportSize({ width, height: 900 });
      await expect(page.getByRole("link", { name: "Business Studio", exact: true })).toHaveAttribute("aria-current", "page");
      await expect(page.getByRole("link", { name: "Lembar kerja", exact: true })).toHaveCount(width >= 1024 ? 1 : 0);
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
      await page.screenshot({ path: testInfo.outputPath(`business-${width}.png`), fullPage: true });
      await page.goto(`${origin}/worksheet`);
      if (width >= 1024) {
        await expect(worksheetCanvas).toBeVisible();
      } else {
        await expect(page.getByText(/lebar minimal 1024 piksel/)).toBeVisible();
        await expect(page.getByRole("button", { name: "Simpan lembar kerja" })).toHaveCount(0);
        await expect(page.getByLabel("Editor lembar kerja")).toHaveCount(0);
      }
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
      await page.screenshot({ path: testInfo.outputPath(`worksheet-${width}.png`), fullPage: true });
      if (width >= 1024) await openBusiness();
      else await page.getByRole("link", { name: "Kembali ke Business Studio" }).click();
      await values();
    }

    const other = await browser.newPage();
    try {
      await other.goto(origin);
      await login(other, "outsider-test", outsider);
      await expect(other.getByRole("button", { name: "Buat ruang kerja" })).toBeVisible();
      const result = await other.evaluate(async id => {
        const { token } = JSON.parse(sessionStorage.getItem("marketstudio.session")!);
        const headers = { Authorization: `Bearer ${token}` };
        const report = await fetch(`/api/workspaces/${id}/reports/daily`, { headers });
        const write = await fetch(`/api/workspaces/${id}/sales`, { method: "POST", headers, body: "{}" });
        const blocked = await fetch("/api/workspaces/demo", { method: "POST", headers, body: "{}" });
        const worksheet = await fetch(`/api/workspaces/${id}/worksheet`, { headers });
        const worksheetSave = await fetch(`/api/workspaces/${id}/worksheet`, {
          method: "PUT", headers, body: JSON.stringify({ cells: {}, revision: 1 }),
        });
        const aiReview = await fetch(`/api/workspaces/${id}/reports/daily/ai-review`, { method: "POST", headers, body: "{}" });
        const aiConfig = await fetch(`/api/workspaces/${id}/ai-review/config`, { headers });
        return {
          worksheet: worksheet.status, worksheetSave: worksheetSave.status, status: report.status,
          cache: report.headers.get("cache-control"), body: await report.json(), write: write.status,
          blocked: blocked.status, aiReview: aiReview.status, aiConfig: aiConfig.status,
        };
      }, workspace);
      expect(result).toMatchObject({
        status: 404, cache: "no-store", body: { code: "workspace_not_found" }, write: 404, blocked: 404,
        worksheet: 404, worksheetSave: 404, aiReview: 404, aiConfig: 404,
      });
    } finally {
      await other.close();
    }
    expect(errors).toEqual([]);
  } finally {
    if (backend!) await stop(backend);
    await stop(web);
    rmSync(dir, { recursive: true, force: true });
  }
});
