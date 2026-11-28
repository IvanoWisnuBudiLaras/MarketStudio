// E2E Playwright verification for Issue #9: Catalog offerings, unit costing, pricing decisions, and archiving.
const assert = require("node:assert/strict");
const { chromium } = require("playwright");

const [base, widthText, evidence] = process.argv.slice(2);
const width = Number(widthText);
assert(base && [390, 1440].includes(width) && evidence,
  "Usage: node scripts/check_offering_pricing.cjs <local-url> <390|1440> <evidence-directory>");
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
    await page.screenshot({ path: `${evidence}/pricing-${state}-${width}.png`, fullPage, animations: "disabled" });
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

  const navigate = async route => {
    if (width === 390) await el("#mobileMenuBtn").click();
    await el(`#appSidebar [data-route="${route}"]`).click();
  };

  try {
    // 1. Initial load & create workspace
    await page.goto(`${base}/#ringkasan`);
    await visible("#onbWsName");
    await el("#onbWsName").fill("Toko Uji Pricing");
    await el("#onboardingWsForm button").click();
    await visible("#kpiGrid .kpi:first-child");
    await layout(1);

    // 2. Navigate to Katalog
    await navigate("katalog");
    await visible("#offSubmitBtn");
    await layout(1);

    // 3. Test Form Draft Persistence across reloads
    await el("#offName").fill("Draft Produk Uji");
    await el("#offPrice").fill("25000");
    await el("#offUnit").fill("pcs");
    // Reload page
    await page.reload();
    await navigate("katalog");
    await visible("#offSubmitBtn");
    assert.equal(await el("#offName").inputValue(), "Draft Produk Uji");
    assert.equal(await el("#offPrice").inputValue(), "25000");

    // 4. Create Goods offering
    await el("#offName").fill("Barang Uji A");
    await el("#offType").selectOption("goods");
    assert(await el("#offServiceCostField").isHidden());
    await el("#offPrice").fill("20000");
    await el("#offUnit").fill("pcs");
    await el("#offSubmitBtn").click();
    await el("#offStatus").filter({ hasText: /Barang Uji A/ }).waitFor();

    // 5. Create Service offering with service cost
    await el("#offName").fill("Jasa Service B");
    await el("#offType").selectOption("service");
    await visible("#offServiceCostField");
    await el("#offServiceCost").fill("35000");
    await el("#offPrice").fill("80000");
    await el("#offUnit").fill("sesi");
    await el("#offSubmitBtn").click();
    await el("#offStatus").filter({ hasText: /Jasa Service B/ }).waitFor();

    // 6. Create Service offering WITHOUT service cost (cost unknown)
    await el("#offName").fill("Jasa Desain C");
    await el("#offType").selectOption("service");
    await visible("#offServiceCostField");
    await el("#offServiceCost").fill("");
    await el("#offPrice").fill("150000");
    await el("#offUnit").fill("desain");
    await el("#offSubmitBtn").click();
    await el("#offStatus").filter({ hasText: /Jasa Desain C/ }).waitFor();

    // 7. Create Hybrid offering
    await el("#offName").fill("Paket Hybrid D");
    await el("#offType").selectOption("hybrid");
    await visible("#offServiceCostField");
    await el("#offServiceCost").fill("25000");
    await el("#offPrice").fill("120000");
    await el("#offUnit").fill("paket");
    await el("#offSubmitBtn").click();
    await el("#offStatus").filter({ hasText: /Paket Hybrid D/ }).waitFor();

    // Verify Table rows and Costing display
    await screenshot("katalog-list");
    const tableText = await el("#offeringTableBody").innerText();
    // Jasa Service B should have Rp 35.000 (Biaya Dasar Jasa) and margin (+Rp 45.000 (+56.25%))
    assert.match(tableText, /Jasa Service B/);
    assert.match(tableText, /35\.000/);
    assert.match(tableText, /45\.000/);
    // Jasa Desain C should have "Belum diketahui" badge
    assert.match(tableText, /Jasa Desain C/);
    assert.match(tableText, /Belum diketahui/);

    // 8. Test Pricing Decision Modal
    const pricingBtn = el('.js-btn-pricing[data-off-id]').first();
    await pricingBtn.click();
    await visible("#pricingModal");
    assert(await el("#pricingModal").evaluate(dialog => dialog.open));
    // Fill new price and strategy notes
    await el("#pricingNewPrice").fill("95000");
    await visible("#pricingPreviewBox");
    assert.match(await el("#pricingPreviewText").innerText(), /95\.000/);
    await el("#pricingStrategyNotes").fill("Kenaikan target margin 2026");
    await el("#savePricingBtn").click();
    await el("#offStatus").filter({ hasText: /Keputusan harga/ }).waitFor();
    assert(await el("#pricingModal").evaluate(dialog => !dialog.open));

    // 9. Test Archiving
    // Count active items
    assert.equal(await el("#offCountActive").innerText(), "4");
    assert.equal(await el("#offCountArchived").innerText(), "0");
    // Archive first item
    const archiveBtn = el('.js-btn-archive').first();
    await archiveBtn.click();
    await el("#offStatus").filter({ hasText: /diarsipkan/ }).waitFor();
    assert.equal(await el("#offCountArchived").innerText(), "1");
    assert.equal(await el("#offCountActive").innerText(), "3");

    // Filter by Archived
    await el('.js-off-filter[data-filter="archived"]').click();
    const archivedRows = await el("#offeringTableBody tr").count();
    assert.equal(archivedRows, 1);

    // Verify archived offering is excluded from Transaksi sale dropdown
    await navigate("transaksi");
    await visible("#saleOffering");
    const saleOptions = await el("#saleOffering option").allTextContents();
    // First item was Barang Uji A and is archived, so it must NOT be in sale options
    assert(!saleOptions.some(opt => opt.includes("Barang Uji A")));

    // 10. Switch back to Katalog and Unarchive
    await navigate("katalog");
    await visible("#offSubmitBtn");
    await el('.js-off-filter[data-filter="archived"]').click();
    const unarchiveBtn = el('.js-btn-archive').first();
    assert.equal(await unarchiveBtn.innerText(), "Aktifkan");
    await unarchiveBtn.click();
    await el("#offStatus").filter({ hasText: /diaktifkan kembali/ }).waitFor();
    assert.equal(await el("#offCountArchived").innerText(), "0");
    assert.equal(await el("#offCountActive").innerText(), "4");

    // Back to Transaksi, now it should appear in options
    await navigate("transaksi");
    await visible("#saleOffering");
    const updatedSaleOptions = await el("#saleOffering option").allTextContents();
    assert(updatedSaleOptions.some(opt => opt.includes("Barang Uji A")));
    await el("#saleOffering").selectOption({ index: 1 });

    await layout(1);
    await screenshot("final");
    console.log(`E2E pricing and archiving checks passed on width ${width}!`);
  } finally {
    await browser.close();
  }
}

run().catch(err => {
  console.error(err);
  process.exit(1);
});
