// Uses two disposable local server processes and a synthetic SQLite fixture.
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
      MARKETSTUDIO_AI_COPY_STUB: mode,
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
  const temporary = await fs.mkdtemp(path.join(os.tmpdir(), "marketstudio-copy-"));
  const db = path.join(temporary, "copy.db");
  const viewport = { width, height: width === 390 ? 844 : 1000 };
  const owner = await browser.newContext({ viewport, permissions: ["clipboard-read", "clipboard-write"] });
  const outsider = await browser.newContext({ viewport });
  let server;
  let failing;
  try {
    server = await startServer(db, "stub_valid");
    const { headers, root } = await seed(owner, server.url, "actor_a", "dev-a-pass");
    const foreign = await seed(outsider, server.url, "actor_b", "dev-b-pass");
    const offer = await owner.request.post(root + "/offerings", { headers, data: {
      name: "Kelas Keramik", offering_type: "service", unit_price_idr: 125000, unit: "sesi",
      description: "Peserta membentuk mangkuk dari tanah liat.",
    } });
    assert.equal(offer.status(), 201);
    const offeringId = (await offer.json()).item.offering_id;
    const page = await owner.newPage();
    page.setDefaultTimeout(7000);
    const errors = [];
    page.on("pageerror", error => { errors.push(error.message); console.error(error); });
    const loc = id => page.locator("#" + id);
    await page.goto(server.url + "/#studio-creative");
    await loc("copyOffering").selectOption(offeringId);
    await loc("copyTone").selectOption("direct");
    await loc("copyAsset").selectOption("asset_bakso_bowl_v1");
    const creating = page.waitForResponse(r => r.url().endsWith("/creative-drafts/caption"));
    await loc("generateCopyBtn").click();
    const generated = await creating;
    assert.equal(generated.status(), 201);
    const { item } = await generated.json();
    await expect(loc("posterCopySource")).toHaveText("Simulasi AI (stub)");
    await expect(loc("posterCaptionInput")).toHaveValue(/Jasa.*Rp 125\.000 \/ sesi\nPeserta membentuk mangkuk/);
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    if (evidence) await loc("posterCaptionPanel").screenshot({ path: path.join(evidence, `stub-${width}.png`) });

    const caption = "Caption dari pemilik.\nHubungi kami untuk bertanya.";
    await loc("posterHeadlineInput").fill("Kelas Keramik untuk pemula");
    await loc("posterCaptionInput").fill(caption);
    await expect(loc("posterCaption")).toHaveText(caption, { useInnerText: true });
    await loc("saveCopyBtn").click();
    await expect(loc("posterStatus")).toHaveText("Draft tersimpan.");
    await page.reload();
    await expect(loc("posterCaptionInput")).toHaveValue(caption);
    await expect(loc("posterHeadlineInput")).toHaveValue("Kelas Keramik untuk pemula");
    await loc("posterCopyCaptionBtn").click();
    await expect(loc("posterCopyStatus")).toHaveText("Caption disalin.");
    assert.equal(await page.evaluate(() => navigator.clipboard.readText()), caption);

    await loc("posterPreviewBtn").click();
    await expect(loc("posterVersion")).toContainText("Draft v2");
    await page.locator(`#catalogChoices input[value="${offeringId}"]`).check();
    await loc("catalogCaption").selectOption(`${item.draft_id}:2`);
    await loc("catalogPreviewBtn").click();
    await expect(page.frameLocator("#catalogFrame").locator(".caption")).toHaveText(caption);
    await expect(loc("catalogPublished")).toBeHidden();

    const foreignPage = await outsider.newPage();
    await foreignPage.goto(server.url + "/#studio-creative");
    await expect(foreignPage.locator("#copyOffering")).toContainText("Tambahkan produk atau jasa");
    await expect(foreignPage.locator("#posterDraftSelect")).toContainText("Belum ada draft");
    const draftPath = "/creative-drafts/" + item.draft_id;
    assert.equal((await outsider.request.get(root + draftPath, { headers: foreign.headers })).status(), 404);
    assert.equal((await outsider.request.get(foreign.root + draftPath, { headers: foreign.headers })).status(), 404);
    assert.equal((await outsider.request.post(foreign.root + "/creative-drafts/caption", {
      headers: foreign.headers,
      data: { offering_id: offeringId, tone: "direct", asset_id: "asset_bakso_bowl_v1" },
    })).status(), 404);

    failing = await startServer(db, width === 390 ? "stub_timeout" : "stub_error");
    await page.goto(failing.url + "/#studio-creative");
    await loc("copyOffering").selectOption(offeringId);
    await loc("copyTone").selectOption("direct");
    await loc("copyAsset").selectOption("asset_beras_harvest_v1");
    const attempted = page.waitForResponse(r => r.url().endsWith("/creative-drafts/caption"));
    await loc("generateCopyBtn").click();
    const failure = await attempted;
    assert.equal(failure.status(), 503);
    assert.equal((await failure.json()).code, width === 390 ? "provider_timeout" : "provider_error");
    await expect(loc("posterStatus")).toContainText("AI belum dapat membuat caption");
    await expect(loc("copyOffering")).toHaveValue(offeringId);
    await expect(loc("copyTone")).toHaveValue("direct");
    await expect(loc("copyAsset")).toHaveValue("asset_beras_harvest_v1");
    await expect(loc("posterCaptionInput")).toHaveValue(caption);
    if (evidence) await loc("posterStatus").screenshot({ path: path.join(evidence, `fallback-${width}.png`) });
    await loc("manualCopyBtn").click();
    await expect(loc("posterCopySource")).toHaveText("Draft manual");
    await loc("posterCaptionInput").fill("Fallback manual tersimpan.");
    await loc("saveCopyBtn").click();
    await expect(loc("posterStatus")).toHaveText("Draft tersimpan.");
    await page.reload();
    await expect(loc("posterCaptionInput")).toHaveValue("Fallback manual tersimpan.");
    assert.deepEqual(errors, []);
    console.log(`PASS ${width}px: stub, facts, edits, save/reload, clipboard, poster, catalog, tenant, provider failure, manual recovery`);
  } finally {
    await owner.close();
    await outsider.close();
    if (failing) await failing.close();
    if (server) await server.close();
    await fs.rm(temporary, { recursive: true, force: true });
  }
}

async function run() {
  const evidence = process.argv[2];
  if (evidence) await fs.mkdir(evidence, { recursive: true });
  const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH });
  try {
    for (const width of [390, 1440]) await verify(browser, width, evidence);
  } finally {
    await browser.close();
  }
}

run().catch(error => { console.error(error); process.exitCode = 1; });
