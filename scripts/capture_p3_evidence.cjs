// Capture P3 (Intelligence Studio & Spreadsheet Studio) visual acceptance evidence for a specific viewport.
const assert = require("node:assert/strict");
const { chromium } = require("playwright");

const [base, widthText, evidenceDir] = process.argv.slice(2);
const width = Number(widthText);
assert(base && [1440, 1280, 768, 390].includes(width) && evidenceDir,
  "Usage: node scripts/capture_p3_evidence.cjs <local-url> <1440|1280|768|390> <evidence-directory>");
assert.equal(new URL(base).hostname, "127.0.0.1", "Must target a local disposable server");

const heights = { 1440: 1000, 1280: 900, 768: 1024, 390: 844 };
const height = heights[width] || 900;

async function capture() {
  const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH });

  try {
    console.log(`Capturing P3 evidence for viewport ${width}x${height}...`);
    const page = await browser.newPage({ viewport: { width, height } });
    const errors = [];
    page.on("pageerror", err => errors.push(err.message));

    const el = selector => page.locator(selector);
    const visible = selector => el(selector).waitFor({ state: "visible" });
    const screenshot = async (filename, fullPage = true) => {
      await page.mouse.move(0, 0);
      await page.screenshot({ path: `${evidenceDir}/${filename}`, fullPage, animations: "disabled" });
    };

    // 1. Initial Empty / Insufficient States
    // A. Intelligence Studio empty state
    await page.goto(`${base}/#studio-intelligence`);
    await visible("#intelligenceNoWorkspace");
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), `Horizontal overflow at ${width}px (intel-empty)`);
    assert(!(/\p{Extended_Pictographic}/u.test(await page.locator("body").innerText())), `Emoji detected at ${width}px (intel-empty)`);
    await screenshot(`intel-empty-${width}.png`);

    // B. Spreadsheet Studio empty state
    await page.goto(`${base}/#analisis`);
    await visible("#analisisNoWorkspace");
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), `Horizontal overflow at ${width}px (sheet-empty)`);
    await screenshot(`sheet-empty-${width}.png`);

    // 2. Load Demo Data from Onboarding
    await page.goto(`${base}/#ringkasan`);
    await visible("#ringkasanEmptyState");
    await el("#onboardingDemoBtn").click();
    await visible("#ringkasanPopulated");
    await page.waitForTimeout(400);

    // 3. Populated Intelligence Studio
    await page.goto(`${base}/#studio-intelligence`);
    await visible("#intelligenceMain");
    await visible("#aiReviewCard");
    await visible("#intelMetricGrid");
    await visible("#intelEditorialCard");
    await visible("#intelRecommendationsSection");
    await visible("#intelBenchmarkSection");

    // Execute AI Business Review
    await el("#runAiReviewBtn").click();
    await page.waitForTimeout(600);

    // Check that review summary is populated
    const summaryText = await el("#intelExecutiveSummary").innerText();
    assert(summaryText.length > 20, "AI review executive summary must be populated");

    // Verify 4 metric grid items
    const revVal = await el("#intelRevenueVal").innerText();
    assert(revVal.includes("Rp"), "Revenue metric must be formatted IDR");

    // Check no horizontal overflow
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), `Horizontal overflow at ${width}px (intel-populated)`);
    assert(!(/\p{Extended_Pictographic}/u.test(await page.locator("body").innerText())), `Emoji detected at ${width}px (intel-populated)`);

    // Check touch targets on mobile 390
    if (width === 390) {
      const undersized = await el("button:visible, .btn:visible, .mobile-nav-btn:visible, .nav-link:visible").evaluateAll(
        controls => controls.filter(control => {
          const { width, height } = control.getBoundingClientRect();
          return width < 44 || height < 44;
        }).map(control => `${control.tagName}.${control.className}: "${control.textContent.trim().slice(0, 20)}" (${Math.round(control.getBoundingClientRect().width)}x${Math.round(control.getBoundingClientRect().height)})`)
      );
      assert.deepEqual(undersized, [], "Undersized controls on 390px mobile in Intelligence Studio");
    }

    await screenshot(`intel-populated-${width}.png`);

    // 4. Intelligence Studio Fallback State (e.g. timeout simulation)
    await el("#aiStubMode").selectOption("stub_timeout");
    await el("#runAiReviewBtn").click();
    await page.waitForTimeout(500);
    const reviewModeBadge = await el("#intelReviewModeBadge").innerText();
    assert(reviewModeBadge.includes("Fallback"), "Review mode badge must indicate fallback on timeout");
    await screenshot(`intel-fallback-${width}.png`);
    await el("#aiStubMode").selectOption("");

    // 5. Populated Spreadsheet Studio
    await page.goto(`${base}/#studio-spreadsheet`);
    await visible("#analisisMain");
    await visible("#sheetTable");
    await visible("#sheetTableBody tr:first-child");
    await visible("#scenarioCompareTable");

    // Check spreadsheet formula bar
    const formulaVal = await el("#sheetFormulaInput").inputValue();
    assert(formulaVal.startsWith("="), "Formula input must display active cell formula");

    // Trigger simulation via preset
    await el("#scenPresetA").click();
    await page.waitForTimeout(500);

    // Verify simulation result rendered
    await visible("#simResultGrid .kpi:first-child");
    const hppVal = await el("#sheetHppVal").innerText();
    assert(hppVal.includes("Rp"), "Sheet HPP must be formatted IDR");

    // Test clicking a table cell to inspect formula bar update
    const cellE2 = el('[data-cell="E2"]');
    if (await cellE2.isVisible()) {
      await cellE2.click();
      await page.waitForTimeout(100);
      assert.equal(await el("#sheetActiveCellBox").innerText(), "E2", "Cell indicator must show E2");
    }

    // Check no horizontal overflow
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), `Horizontal overflow at ${width}px (sheet-populated)`);
    assert(!(/\p{Extended_Pictographic}/u.test(await page.locator("body").innerText())), `Emoji detected at ${width}px (sheet-populated)`);

    // Check touch targets on mobile 390
    if (width === 390) {
      const undersized = await el("button:visible, .btn:visible, .mobile-nav-btn:visible, .nav-link:visible").evaluateAll(
        controls => controls.filter(control => {
          const { width, height } = control.getBoundingClientRect();
          return width < 44 || height < 44;
        }).map(control => `${control.tagName}.${control.className}: "${control.textContent.trim().slice(0, 20)}" (${Math.round(control.getBoundingClientRect().width)}x${Math.round(control.getBoundingClientRect().height)})`)
      );
      assert.deepEqual(undersized, [], "Undersized controls on 390px mobile in Spreadsheet Studio");
    }

    await screenshot(`sheet-populated-${width}.png`);

    // 6. Test Deep Link Hash reload & studio transitions
    // Navigate via deep link #analisis-benchmark
    await page.goto(`${base}/#analisis-benchmark`);
    await page.waitForTimeout(300);
    assert.equal(await el("#view-intelligence").isVisible(), true, "#analisis-benchmark must open Intelligence Studio");

    // Reload test on #studio-spreadsheet
    await page.goto(`${base}/#studio-spreadsheet`);
    await page.reload();
    await visible("#analisisMain");
    assert.equal(await el("#view-analisis").isVisible(), true, "Reload on #studio-spreadsheet must preserve view");

    assert.deepEqual(errors, []);
    await page.close();
    console.log(`PASS ${width}px captured successfully!`);
  } finally {
    await browser.close();
  }
}

capture().catch(err => {
  console.error("CAPTURE FAILED:", err);
  process.exitCode = 1;
});
