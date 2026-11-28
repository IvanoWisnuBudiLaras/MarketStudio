// Capture P1-P2 visual acceptance evidence for a specific viewport.
const assert = require("node:assert/strict");
const { chromium } = require("playwright");

const [base, widthText, evidenceDir] = process.argv.slice(2);
const width = Number(widthText);
assert(base && [1440, 1280, 768, 390].includes(width) && evidenceDir,
  "Usage: node scripts/capture_p1_p2_evidence.cjs <local-url> <1440|1280|768|390> <evidence-directory>");
assert.equal(new URL(base).hostname, "127.0.0.1", "Must target a local disposable server");

const heights = { 1440: 1000, 1280: 900, 768: 1024, 390: 844 };
const height = heights[width] || 900;

async function capture() {
  const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH });

  try {
    console.log(`Capturing evidence for viewport ${width}x${height}...`);
    const page = await browser.newPage({ viewport: { width, height } });
    const errors = [];
    page.on("pageerror", err => errors.push(err.message));

    const el = selector => page.locator(selector);
    const visible = selector => el(selector).waitFor({ state: "visible" });
    const screenshot = async (filename, fullPage = true) => {
      await page.mouse.move(0, 0);
      await page.screenshot({ path: `${evidenceDir}/${filename}`, fullPage, animations: "disabled" });
    };

    // 1. Initial Empty State
    await page.goto(`${base}/#ringkasan`);
    await visible("#ringkasanEmptyState");
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), `Horizontal overflow at ${width}px`);
    assert(!(/\p{Extended_Pictographic}/u.test(await page.locator("body").innerText())), `Emoji detected at ${width}px`);

    if (width === 390) {
      const undersized = await el("button:visible, .btn:visible, .mobile-nav-btn:visible, .nav-link:visible").evaluateAll(
        controls => controls.filter(control => {
          const { width, height } = control.getBoundingClientRect();
          return width < 44 || height < 44;
        }).map(control => control.textContent.trim())
      );
      assert.deepEqual(undersized, [], "Undersized controls on 390px mobile");
    }

    await screenshot(`empty-${width}.png`);

    // 2. Load Demo Data
    await el("#onboardingDemoBtn").click();
    await visible("#ringkasanPopulated");
    await visible("#kpiGrid .kpi:first-child");
    await page.waitForTimeout(400);

    // Verify 4 KPIs in overview
    const kpiText = await el("#kpiGrid").innerText();
    assert.match(kpiText, /Arus kas bersih/, "Arus kas bersih KPI must be present");
    assert.match(kpiText, /Laba kotor/, "Laba kotor KPI must be present");
    assert.match(kpiText, /Omzet/, "Omzet KPI must be present");
    assert.match(kpiText, /Nilai persediaan/, "Nilai persediaan KPI must be present");

    // Verify cash breakdown rows
    await visible("#cashFlowSummaryBreakdown");

    assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), `Horizontal overflow populated at ${width}px`);
    await screenshot(`populated-${width}.png`);

    // 3. For Desktop (1440 and 1280), test sidebar collapse to ~64px icon rail
    if (width >= 1200) {
      const collapseBtn = el("#sidebarCollapseBtn");
      await collapseBtn.click();
      await page.waitForTimeout(300);
      assert.equal(await el("#appSidebar").evaluate(aside => aside.classList.contains("collapsed")), true);
      const sidebarWidth = await el("#appSidebar").evaluate(aside => aside.getBoundingClientRect().width);
      assert(Math.abs(sidebarWidth - 64) <= 4, `Sidebar width when collapsed must be ~64px, got ${sidebarWidth}`);
      await screenshot(`collapsed-${width}.png`);
      // Expand again
      await collapseBtn.click();
      await page.waitForTimeout(200);
    }

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
