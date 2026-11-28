// Uses disposable local server processes and a synthetic SQLite fixture.
const { createHash } = require("node:crypto");
const assert = require("node:assert/strict");
const { spawn } = require("node:child_process");
const { once } = require("node:events");
const fs = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");
const { chromium, expect } = require("playwright/test");

async function startServer(db, mode) {
  const server = spawn("python3", ["-u", "-c", [
    "import sys; from app.server import create_server",
    "s = create_server(port=0, db_path=sys.argv[1])",
    "print(s.server_port); s.serve_forever()",
  ].join("; "), db], {
    env: {
      ...process.env,
      MARKETSTUDIO_DB_BACKEND: "sqlite",
      MARKETSTUDIO_ENV: "development",
      MARKETSTUDIO_QUIET_LOGS: "1",
      MARKETSTUDIO_AI_IMAGE_STUB: mode,
    },
    stdio: ["ignore", "pipe", "inherit"],
  });
  const exited = once(server, "exit");
  const [port] = await Promise.race([
    once(server.stdout, "data"),
    exited.then(([code]) => { throw new Error(`Fixture server exited with ${code}`); }),
  ]);
  return {
    url: `http://127.0.0.1:${String(port).trim()}`,
    close: async () => { server.kill(); await exited; },
  };
}

async function seed(context, origin, actor, passcode) {
  const login = await context.request.post(origin + "/v1/sessions", { data: { actor_id: actor, passcode } });
  assert.equal(login.status(), 201);
  const token = (await login.json()).item.token;
  const headers = { Authorization: `Bearer ${token}` };
  const ws = await context.request.post(origin + "/v1/workspaces", {
    headers, data: { name: `Usaha sintetis ${actor}` },
  });
  assert.equal(ws.status(), 201);
  const workspace = (await ws.json()).item.workspace_id;
  await context.addInitScript(({ token, workspace }) => {
    if (window !== window.top) return;
    localStorage.setItem("marketstudio_session_token", token);
    localStorage.setItem("marketstudio_active_workspace_id", workspace);
  }, { token, workspace });
  return { headers, root: `${origin}/v1/workspaces/${workspace}` };
}

async function verify(browser, width, evidence) {
  const temporary = await fs.mkdtemp(path.join(os.tmpdir(), "marketstudio-image-"));
  const db = path.join(temporary, "image.db");
  const viewport = { width, height: width === 390 ? 844 : 1000 };
  const owner = await browser.newContext({ viewport });
  const outsider = await browser.newContext({ viewport });
  let server;
  let failing;
  try {
    server = await startServer(db, "slow");
    const { headers, root } = await seed(owner, server.url, "actor_a", "dev-a-pass");
    const foreign = await seed(outsider, server.url, "actor_b", "dev-b-pass");
    const offer = await owner.request.post(root + "/offerings", { headers, data: {
      name: "Kelas Keramik", offering_type: "service", unit_price_idr: 125000, unit: "sesi",
    } });
    assert.equal(offer.status(), 201);
    const offeringId = (await offer.json()).item.offering_id;
    const page = await owner.newPage();
    page.setDefaultTimeout(7000);
    const errors = [];
    page.on("pageerror", error => errors.push(error.message));
    const loc = id => page.locator("#" + id);
    await page.goto(server.url + "/#studio-creative");
    const sample = page.waitForResponse(r => r.url().endsWith("/creative-drafts/sample"));
    await loc("posterSampleBtn").click();
    const draft = (await (await sample).json()).item;
    await loc("imageOffering").selectOption(offeringId);
    await loc("imageStyle").selectOption("illustration");

    const cancelled = page.waitForResponse(r => r.url().endsWith("/generate"));
    await loc("generateImageBtn").click();
    await loc("cancelImageBtn").click();
    await expect(loc("posterImageStatus")).toHaveText("Pembuatan gambar dibatalkan.");
    assert.equal((await cancelled).status(), 409);
    await expect(loc("generatedImagePreview")).toBeHidden();

    const pending = page.waitForResponse(r => r.url().endsWith("/generate"));
    await loc("generateImageBtn").click();
    const response = await pending;
    assert.equal(response.status(), 201);
    const { item } = await response.json();
    await expect(loc("posterImageStatus")).toHaveText("Simulasi gambar AI (stub)");
    await expect(loc("generatedImagePreview")).toBeVisible();
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    if (evidence) await loc("posterImagePanel").screenshot({ path: path.join(evidence, `stub-${width}.png`) });

    const imagePath = "/creative-images/" + item.asset_id;
    assert.equal((await outsider.request.post(root + imagePath + "/cancel", { headers: foreign.headers })).status(), 404);
    assert.equal((await outsider.request.post(root + imagePath + "/generate", { headers: foreign.headers })).status(), 404);
    assert.equal((await outsider.request.post(root + imagePath + "/generate")).status(), 401);
    const patchPath = "/creative-drafts/" + draft.draft_id;
    assert.equal((await outsider.request.patch(root + patchPath, {
      headers: foreign.headers, data: { asset_id: item.asset_id, expected_version: draft.version },
    })).status(), 404);
    const foreignDraft = (await (await outsider.request.post(foreign.root + "/creative-drafts/sample", {
      headers: foreign.headers,
    })).json()).item;
    assert.equal((await outsider.request.patch(foreign.root + "/creative-drafts/" + foreignDraft.draft_id, {
      headers: foreign.headers, data: { asset_id: item.asset_id, expected_version: foreignDraft.version },
    })).status(), 404);
    const foreignAssets = await (await outsider.request.get(foreign.root + "/creative-assets", { headers: foreign.headers })).json();
    assert.ok(!foreignAssets.items.some(asset => asset.asset_id === item.asset_id));

    await loc("applyImageBtn").click();
    await expect(loc("posterStatus")).toHaveText("Gambar dipasang ke draft. Tampilkan pratinjau sebelum mengunduh.");
    await expect(loc("posterAssetSelect")).toHaveValue(item.asset_id);
    await loc("posterFormat").selectOption(width === 390 ? "png" : "svg");
    const previewed = page.waitForResponse(r => r.url().endsWith(patchPath + "/preview"));
    await loc("posterPreviewBtn").click();
    const preview = (await (await previewed).json()).item;
    assert.equal(preview.draft.asset_id, item.asset_id);
    assert.equal(preview.draft.version, draft.version + 1);
    const downloading = page.waitForEvent("download");
    await loc("posterExportBtn").click();
    const download = await downloading;
    const bytes = await fs.readFile(await download.path());
    const previewBytes = Buffer.from(preview.preview_data_url.split(",")[1], "base64");
    assert.deepEqual(bytes, previewBytes);
    assert.equal(createHash("sha256").update(bytes).digest("hex"), preview.preview_sha256);

    failing = await startServer(db, width === 390 ? "failure" : "timeout");
    await page.goto(failing.url + "/#studio-creative");
    await expect(loc("posterAssetSelect")).toHaveValue(item.asset_id);
    await loc("generateImageBtn").click();
    await expect(loc("posterImageStatus")).toHaveText(/Penyedia gambar .*Coba lagi atau pilih aset berizin/);
    await expect(loc("generateImageBtn")).toBeEnabled();
    await expect(loc("generatedImagePreview")).toBeHidden();
    if (evidence) await loc("posterImagePanel").screenshot({ path: path.join(evidence, `fallback-${width}.png`) });
    await loc("posterAssetSelect").selectOption("asset_catering_tray_v1");
    const fallback = page.waitForResponse(r => r.url().endsWith(patchPath + "/preview"));
    await loc("posterPreviewBtn").click();
    const manual = (await (await fallback).json()).item;
    assert.equal(manual.asset.asset_id, "asset_catering_tray_v1");
    assert.equal(manual.asset.asset_license, "CC0-1.0");
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    assert.deepEqual(errors, []);
    console.log(`Chromium ${width}px: cancellation, retry, stub, preview/export, tenant isolation, and licensed fallback passed`);
  } finally {
    await owner.close();
    await outsider.close();
    if (failing) await failing.close();
    if (server) await server.close();
    await fs.rm(temporary, { recursive: true, force: true });
  }
}

async function main() {
  const evidence = process.argv[2];
  if (evidence) await fs.mkdir(evidence, { recursive: true });
  const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH });
  try {
    for (const width of [390, 1440]) await verify(browser, width, evidence);
  } finally {
    await browser.close();
  }
}

main().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
