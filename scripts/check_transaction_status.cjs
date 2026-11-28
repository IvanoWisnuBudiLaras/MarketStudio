// E2E Playwright verification for Issue #7: Transaction status feedback, double submit prevention,
// input retention on network failure, and consistent idempotency key retry.
const assert = require("node:assert/strict");
const { chromium } = require("playwright");

const [base, widthText, evidence] = process.argv.slice(2);
const width = Number(widthText);
assert(base && [390, 1440].includes(width) && evidence,
  "Usage: node scripts/check_transaction_status.cjs <local-url> <390|1440> <evidence-directory>");
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
    await page.screenshot({ path: `${evidence}/tx-status-${state}-${width}.png`, fullPage, animations: "disabled" });
  };

  async function layout() {
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
      "Horizontal overflow detected");
    assert(!(/\p{Extended_Pictographic}/u.test(await page.locator("body").innerText())),
      "Emoji detected in UI");
    if (width === 390) {
      const undersized = await el("button:visible, .btn:visible, .mobile-nav-btn:visible, .nav-link:visible").evaluateAll(
        controls => controls.filter(control => {
          const { width, height } = control.getBoundingClientRect();
          return width < 44 || height < 44;
        }).map(control => control.textContent.trim())
      );
      assert.deepEqual(undersized, [], "Undersized touch target detected");
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
    await el("#onbWsName").fill("Toko Status Uji");
    await el("#onboardingWsForm button").click();
    await visible("#kpiGrid .kpi:first-child");

    // 2. Add an offering in Katalog & Stok
    await navigate("katalog");
    await visible("#offSubmitBtn");
    await el("#offName").fill("Kopi Susu Uji");
    await el("#offType").selectOption("goods");
    await el("#offUnit").fill("cup");
    await el("#offPrice").fill("15000");
    await el("#offSubmitBtn").click();
    await el("#offStatus").filter({ hasText: /tersimpan/ }).waitFor();

    // 3. Purchase initial stock (50 cups @ 5000)
    await navigate("transaksi");
    await visible("#tabPurchaseBtn");
    await el("#tabPurchaseBtn").click();
    await page.waitForURL("**/#transaksi-pembelian");
    await visible("#purOffering");
    await el("#purOffering").selectOption({ index: 1 });
    await visible("#purQty");
    await el("#purQty").fill("50");
    await el("#purCost").fill("250000");
    await el("#purSubmitBtn").click();
    await el("#purStatus").filter({ hasText: /Pembelian tersimpan/ }).waitFor();

    // Switch back to Penjualan tab
    await el("#tabSaleBtn").click();
    await page.waitForURL("**/#transaksi");
    await visible("#saleOffering");
    await el("#saleOffering").selectOption({ index: 1 });
    await visible("#saleQty");
    await el("#saleQty").fill("2");
    await el("#salePrice").fill("30000");

    // 4. Scenario A: In-flight status and button disabled on slow response
    let delayedRouteCalled = false;
    await page.route("**/v1/workspaces/*/sales", async route => {
      delayedRouteCalled = true;
      await new Promise(r => setTimeout(r, 600));
      await route.continue();
    });

    const submitBtn = el("#saleSubmitBtn");
    await submitBtn.click();

    // Assert in-flight state immediately while request is delayed
    assert(await submitBtn.isDisabled(), "Submit button must be disabled during in-flight save");
    assert.equal(await submitBtn.getAttribute("aria-busy"), "true", "Submit button must have aria-busy=true");
    assert.equal(await el("#saleForm").getAttribute("aria-busy"), "true", "Form must have aria-busy=true");
    const inFlightStatus = el("#saleStatus");
    assert.match(await inFlightStatus.innerText(), /Sedang menyimpan penjualan/, "Status must announce saving in flight");
    assert(await inFlightStatus.evaluate(node => node.classList.contains("info")), "Status must have info class");
    await layout();
    await screenshot("inflight");

    // Rapid second click during in-flight must be ignored
    await submitBtn.click({ force: true }).catch(() => {});

    // Await success completion
    await el("#saleStatus").filter({ hasText: /Penjualan tersimpan/ }).waitFor();
    assert.equal(await submitBtn.isDisabled(), false, "Submit button must be re-enabled after completion");
    assert.equal(await submitBtn.getAttribute("aria-busy"), null, "Submit button aria-busy must be cleared");
    assert.equal(await el("#saleForm").getAttribute("aria-busy"), null, "Form aria-busy must be cleared");
    await el("#txRecentBody tr").first().filter({ hasText: /30\.000/ }).waitFor();
    await screenshot("success-initial");
    await page.unroute("**/v1/workspaces/*/sales");

    // 5. Scenario B: Network failure / connection loss & Input Retention
    await el("#saleQty").fill("3");
    await el("#salePrice").fill("45000");

    // Abort network request to simulate connection drop / offline
    await page.route("**/v1/workspaces/*/sales", async route => {
      await route.abort("failed");
    });

    await submitBtn.click();

    // Await error status
    await el("#saleStatus").filter({ hasText: /Koneksi terganggu/ }).waitFor();
    const errStatus = el("#saleStatus");
    assert(await errStatus.evaluate(node => node.classList.contains("err")), "Status must have err class on network failure");
    assert.equal(await errStatus.getAttribute("role"), "alert", "Status must set role=alert on error");

    // CRITICAL: Verify input retention (inputs must NOT be cleared or reset)
    assert.equal(await el("#saleQty").inputValue(), "3", "Quantity input must be retained on network failure");
    assert.equal(await el("#salePrice").inputValue(), "45000", "Price input must be retained on network failure");

    // Verify 'Coba Lagi' action button exists and meets touch target size
    const retryBtn = el("#saleRetryBtn");
    await visible("#saleRetryBtn");
    assert.equal(await retryBtn.innerText(), "Coba Lagi");
    await layout();
    await screenshot("error-retry");
    await page.unroute("**/v1/workspaces/*/sales");

    // 6. Scenario C: Response lost scenario (commit succeeds on server, response drops)
    // Retry with same Idempotency-Key must return existing transaction without duplicate mutations.
    let capturedIdempotencyKeys = [];
    let serverDropSimulated = true;

    await page.route("**/v1/workspaces/*/sales", async route => {
      const headers = route.request().headers();
      capturedIdempotencyKeys.push(headers["idempotency-key"]);
      if (serverDropSimulated) {
        serverDropSimulated = false;
        // Let server commit by making the actual fetch in background, then abort the client response
        const postData = route.request().postData();
        const url = route.request().url();
        await fetch(url, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Authorization": headers["authorization"] || "",
            "Idempotency-Key": headers["idempotency-key"] || ""
          },
          body: postData
        });
        // Abort the client's connection so client experiences response lost
        await route.abort("connectionreset");
      } else {
        await route.continue();
      }
    });

    // Click 'Coba Lagi' to start retry
    await retryBtn.click();

    // Client sees network error from the lost response
    await el("#saleStatus").filter({ hasText: /Koneksi terganggu/ }).waitFor();
    assert.equal(await el("#saleQty").inputValue(), "3", "Inputs remain retained after dropped response");
    assert.equal(await el("#salePrice").inputValue(), "45000");

    // Click 'Coba Lagi' again - now route will forward to server with the SAME Idempotency-Key
    await el("#saleRetryBtn").click();

    // Client receives replayed 201 response and shows success
    await el("#saleStatus").filter({ hasText: /Penjualan tersimpan/ }).waitFor();
    assert.equal(await el("#saleRetryBtn").count(), 0, "Retry button must be cleared on success");

    // Assert that the exact same Idempotency-Key was preserved across retries
    assert.equal(capturedIdempotencyKeys.length, 2, "Should have made 2 retry attempts");
    assert.ok(capturedIdempotencyKeys[0], "First attempt must have an Idempotency-Key");
    assert.equal(capturedIdempotencyKeys[0], capturedIdempotencyKeys[1],
      "Idempotency-Key must remain invariant across retries of the same intent");

    await page.unroute("**/v1/workspaces/*/sales");

    // 7. Scenario D: Purchase Form failure, retention & retry
    await el("#tabPurchaseBtn").click();
    await page.waitForURL("**/#transaksi-pembelian");
    await el("#purOffering").selectOption({ index: 1 });
    await el("#purQty").fill("10");
    await el("#purCost").fill("50000");

    let purFailOnce = true;
    let purIdempotencyKeys = [];
    await page.route("**/v1/workspaces/*/purchases", async route => {
      purIdempotencyKeys.push(route.request().headers()["idempotency-key"]);
      if (purFailOnce) {
        purFailOnce = false;
        await route.abort("failed");
      } else {
        await route.continue();
      }
    });

    await el("#purSubmitBtn").click();
    await el("#purStatus").filter({ hasText: /Koneksi terganggu/ }).waitFor();
    assert.equal(await el("#purQty").inputValue(), "10", "Purchase qty retained");
    assert.equal(await el("#purCost").inputValue(), "50000", "Purchase cost retained");
    await visible("#purRetryBtn");
    await layout();

    // Click purchase Coba Lagi
    await el("#purRetryBtn").click();
    await el("#purStatus").filter({ hasText: /Pembelian tersimpan/ }).waitFor();
    assert.equal(await el("#purRetryBtn").count(), 0);
    assert.equal(purIdempotencyKeys.length, 2);
    assert.equal(purIdempotencyKeys[0], purIdempotencyKeys[1], "Purchase Idempotency-Key preserved on retry");
    await page.unroute("**/v1/workspaces/*/purchases");

    // 8. Scenario E: Keyboard submission
    await el("#tabSaleBtn").click();
    await page.waitForURL("**/#transaksi");
    await el("#saleQty").focus();
    await el("#saleQty").fill("1");
    await el("#salePrice").focus();
    await el("#salePrice").fill("15000");
    // Press Enter to submit
    await page.keyboard.press("Enter");
    await el("#saleStatus").filter({ hasText: /Penjualan tersimpan/ }).waitFor();

    await layout();
    await screenshot("final");

    assert.deepEqual(errors, [], `Unexpected page errors: ${errors.join(", ")}`);
    console.log(`PASS ${width}px: transaction status, double submit prevention, input retention, idempotency retry`);
  } finally {
    await browser.close();
  }
}

run().catch(err => {
  console.error(err);
  process.exit(1);
});
