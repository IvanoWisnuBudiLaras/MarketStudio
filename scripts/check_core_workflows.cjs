// Run against an isolated, empty MarketStudio SQLite database per viewport.
const assert = require("node:assert/strict");
const { chromium } = require("playwright");

const [base, widthText, evidence] = process.argv.slice(2);
const width = Number(widthText);
assert(base && [390, 1440].includes(width) && evidence,
  "Usage: node scripts/check_core_workflows.cjs <local-url> <390|1440> <evidence-directory>");
assert.equal(new URL(base).hostname, "127.0.0.1", "Use a disposable local server");

async function run() {
  const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH });
  const page = await browser.newPage({ viewport: { width, height: width === 390 ? 844 : 1000 } });
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  const el = selector => page.locator(selector);
  const visible = selector => el(selector).waitFor({ state: "visible" });
  const screenshot = async (state, fullPage = true) => {
    await page.mouse.move(0, 0);
    await page.screenshot({ path: `${evidence}/after-${state}-${width}.png`, fullPage, animations: "disabled" });
  };
  const primary = '.top-bar .btn-primary:visible, main .btn-primary:visible';

  async function layout(count) {
    assert.equal(await el(primary).count(), count);
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));
    assert(!(/\p{Extended_Pictographic}/u.test(await page.locator("body").innerText())));
    if (width === 390) {
      const undersized = await el("button:visible, .btn:visible, .mobile-nav-btn:visible, .nav-link:visible").evaluateAll(
        controls => controls.filter(control => {
          const { width, height } = control.getBoundingClientRect();
          return width < 44 || height < 44;
        }).map(control => control.textContent.trim())
      );
      assert.deepEqual(undersized, []);
    }
  }

  try {
    const [workspaces] = await Promise.all([
      page.waitForResponse(response => response.url().endsWith("/v1/workspaces")),
      page.goto(`${base}/#ringkasan`)
    ]);
    assert.deepEqual((await workspaces.json()).items, []);
    const brand = width === 390 ? ".mobile-brand-image" : ".brand-image";
    await visible(brand);
    assert(await el(brand).evaluate(image => image.complete && image.naturalWidth > 0));
    await layout(1);
    await screenshot("empty");
    await el("#onbWsName").fill("A");
    await el("#onboardingWsForm button").click();
    await visible("#onbWsNameErr");
    assert.equal(await el("#onbWsName").inputValue(), "A");
    await el("#onbWsName").fill("Usaha Uji UX");
    const [created] = await Promise.all([
      page.waitForResponse(response => response.url().endsWith("/v1/workspaces") && response.request().method() === "POST"),
      el("#onboardingWsForm button").click()
    ]);
    const { item: owner } = await created.json();
    await visible("#kpiGrid .kpi:first-child");
    await el("#homeTransactionBtn").filter({ hasText: "Tambah produk atau jasa" }).waitFor();
    assert.match(await el("#homeRecentList").innerText(), /Belum ada transaksi/);
    assert(await el("#demoContextBanner").isHidden());

    const navigate = async route => {
      if (width === 390) await el("#mobileMenuBtn").click();
      await el(`#appSidebar [data-route="${route}"]`).click();
    };
    if (width === 390) {
      await el("#mobileMenuBtn").focus();
      await page.keyboard.press("Enter");
      assert(await el("#closeDrawerBtn").evaluate(button => button.matches(":focus-visible")));
      await page.keyboard.press("Escape");
      assert(await el("#mobileMenuBtn").evaluate(button => button === document.activeElement));
    }
    await navigate("profil");
    await layout(1);
    const [loaded] = await Promise.all([
      page.waitForResponse(response => response.url().endsWith("/v1/workspaces/demo")),
      el("#loadDemoBtn").click()
    ]);
    const { item: demo } = await loaded.json();
    await el("#demoStatus").filter({ hasText: /berhasil dimuat/ }).waitFor();
    await el("#loadDemoBtn").click();
    await el("#demoStatus").filter({ hasText: /tidak ada data duplikat/ }).waitFor();
    await navigate("ringkasan");
    await visible("#homeTransactionBtn");
    assert.equal(await el("#reportDate").inputValue(), demo.demo_date);
    assert.match(await el("#kpiGrid").innerText(), /Arus kas bersih\s+-Rp\s*150\.000[\s\S]*Laba kotor\s+Rp\s*24\.000/);
    assert.match(await el("#stockValue").innerText(), /174\.000/);
    assert(await el(".stock-summary").evaluate(table => table.scrollWidth <= table.clientWidth));
    assert.equal(await el("#homeRecentList li").count(), 3);
    assert.match(await el("#quickRevenue").innerText(), /60\.000/);
    assert.match(await el("#quickCash").innerText(), /150\.000/);
    await layout(1);
    await screenshot("demo");

    await el("#homeTransactionBtn").click();
    assert.equal(await el("#pageTitle").innerText(), "Transaksi");
    assert(await el("#saleQty").isHidden());
    await el("#tabSaleBtn").focus();
    await page.keyboard.press("ArrowRight");
    await page.waitForURL("**/#transaksi-pembelian");
    await visible("#purOffering");
    await page.keyboard.press("ArrowLeft");
    await page.waitForURL("**/#transaksi");
    await el("#saleOffering").selectOption({ index: 1 });
    await el("#saleQty").fill("999");
    await el("#salePrice").fill("23000");
    await layout(1);
    await el("#saleSubmitBtn").click();
    await el("#saleQtyErr").filter({ hasText: /Kurangi jumlah/ }).waitFor();
    assert.equal(await el("#saleQty").inputValue(), "999");
    assert.equal(await el("#salePrice").inputValue(), "23000");
    assert(await el("#saleQty").evaluate(input => input === document.activeElement));
    await screenshot("validation");
    await el("#saleQty").fill("1");
    await el("#salePrice").fill("15000");
    await el("#saleSubmitBtn").click();
    await el("#saleStatus").filter({ hasText: /Penjualan tersimpan/ }).waitFor();
    await el("#txRecentBody tr").first().filter({ hasText: /15\.000/ }).waitFor();
    await page.getByRole("link", { name: "Lihat laporan di Beranda" }).click();
    await el("#homeRecentList li").first().filter({ hasText: /15\.000/ }).waitFor();
    assert.match(await el("#kpiGrid").innerText(), /135\.000/);
    await screenshot("result");

    await navigate("katalog");
    await layout(1);
    await visible("#offSubmitBtn");
    await navigate("analisis");
    await layout(1);
    await el("#tabBenchBtn").click();
    await page.waitForURL("**/#analisis-benchmark");
    await el("#benchSourceKind").selectOption("manual_fallback");
    await visible("#benchManualWrap");
    await layout(1);

    await navigate("studio-creative");
    await visible("#posterSampleBtn");
    await el("#posterSampleBtn").click();
    await el("#posterPreviewBtn").click();
    await visible("#posterPreviewImage");
    const [download] = await Promise.all([page.waitForEvent("download"), el("#posterExportBtn").click()]);
    assert.match(download.suggestedFilename(), /\.svg$/);
    assert.equal(await download.failure(), null);

    const settingsButton = el("#openSummaryBtn");
    const drawer = el("#summaryDrawer");
    const closeDrawer = page.getByRole("button", { name: "Tutup pengaturan ringkasan" });
    const recentToggle = el('[data-summary-module="homeRecentCard"]');
    await navigate("ringkasan");
    await settingsButton.focus();
    await page.keyboard.press("Enter");
    await drawer.waitFor();
    assert(await closeDrawer.evaluate(button => button === document.activeElement && button.matches(":focus-visible")));
    await screenshot("drawer", false);
    if (width === 390) {
      await page.setViewportSize({ width, height: 340 });
      assert(await drawer.evaluate(panel => panel.scrollHeight > panel.clientHeight));
      await closeDrawer.click();
      await page.setViewportSize({ width, height: 844 });
      await settingsButton.click();
    }
    await recentToggle.focus();
    await page.keyboard.press("Space");
    assert(await el("#homeRecentCard").isHidden());
    assert.equal(await recentToggle.isChecked(), false);
    await page.keyboard.press("Escape");
    await drawer.waitFor({state: "hidden"});
    await page.waitForFunction(() => document.activeElement?.id === "openSummaryBtn");
    await page.reload();
    await visible("#kpiGrid .kpi:first-child");
    assert(await el("#homeRecentCard").isHidden());

    await navigate("profil");
    await el("#workspaceSelect").selectOption(owner.workspace_id);
    await navigate("ringkasan");
    await el("#homeRecentList li").filter({ hasText: /Belum ada transaksi/ }).waitFor();
    assert(await el("#demoContextBanner").isHidden());
    await settingsButton.click();
    assert(await recentToggle.isChecked());
    const quickToggle = el('[data-summary-module="quickMetrics"]');
    await quickToggle.uncheck();
    await closeDrawer.click();
    assert(await el("#quickMetrics").isHidden());

    await navigate("profil");
    await el("#workspaceSelect").selectOption(demo.workspace.workspace_id);
    await navigate("ringkasan");
    await visible("#quickMetrics");
    assert(await el("#homeRecentCard").isHidden());
    await settingsButton.click();
    await el("#restoreSummaryBtn").click();
    assert(await recentToggle.isChecked());
    await closeDrawer.click();
    await visible("#homeRecentCard");

    await navigate("profil");
    await el("#workspaceSelect").selectOption(owner.workspace_id);
    await navigate("katalog");
    await el("#offName").fill("Beras uji");
    await el("#offPrice").fill("14500");
    await el("#offUnit").fill("kg");
    await el("#offSubmitBtn").click();
    await el("#offStatus").filter({ hasText: /tersimpan/ }).waitFor();
    await navigate("ringkasan");
    await el("#homeStockAlert").filter({ hasText: "Stok habis saat ini · Beras uji" }).waitFor();
    assert(await el("#quickMetrics").isHidden());
    assert.deepEqual(errors, []);
    console.log(`PASS ${width}px: empty, demo and replay, sale and report, navigation, poster SVG, drawer focus, preferences and workspace isolation, out-of-stock`);
  } finally {
    await browser.close();
  }
}

run().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
