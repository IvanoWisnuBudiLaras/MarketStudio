// Run against a disposable local SQLite server.
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const { chromium } = require("playwright");

const [base, widthText, evidence] = process.argv.slice(2);
const width = Number(widthText);
assert(base && [390, 1440].includes(width) && evidence,
  "Usage: node scripts/check_public_catalog.cjs <local-url> <390|1440> <evidence-directory>");
assert.equal(new URL(base).hostname, "127.0.0.1");

const cachePolicy = "no-store, no-cache, must-revalidate";
async function run() {
  const viewport = { width, height: width === 390 ? 844 : 1000 };
  const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH });
  try {
    const owner = await browser.newContext({ viewport, permissions: ["clipboard-read", "clipboard-write"] });
    const page = await owner.newPage();
    page.setDefaultTimeout(8000);
    const anonymous = await browser.newContext({ viewport });
    const errors = [];
    page.on("pageerror", error => errors.push(error.message));
    const select = selector => page.locator(selector);
    const status = (id, text) => select(id).filter({ hasText: text }).waitFor();
    const noOverflow = async target =>
      assert(await target.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));

    await page.goto(base + "/#profil");
    await select("#loadDemoBtn").click();
    await status("#demoStatus", /berhasil dimuat|tidak ada data duplikat/);
    if (width === 390) await select("#mobileMenuBtn").click();
    await select('#appSidebar [data-route="studio-creative"]').click();

    const offering = select("#catalogChoices label").filter({ hasText: "Bakso Urat" });
    await offering.locator("input").check();
    await select("#catalogArtwork").selectOption("asset_bakso_bowl_v1");
    await select("#catalogPreviewBtn").click();
    await status("#catalogPublishStatus", "Pratinjau siap ditinjau.");
    const preview = page.frameLocator("#catalogFrame");
    await preview.getByRole("heading", { name: "Bakso Urat" }).waitFor();
    assert.equal(await preview.getByRole("listitem").count(), 1);
    assert(await select("#catalogReviewTitle").evaluate(heading => heading === document.activeElement));
    await noOverflow(page);
    await noOverflow(preview.locator("html"));
    if (width === 390) {
      const tooSmall = await select("#posterMain button:visible, #catalogArtwork, .catalog-choice").evaluateAll(
        controls => controls.filter(control => {
          const box = control.getBoundingClientRect();
          return box.width < 44 || box.height < 44;
        }).map(control => control.textContent.trim())
      );
      assert.deepEqual(tooSmall, []);
    }
    assert(!/\p{Extended_Pictographic}/u.test(await select("#posterMain").innerText()));
    await select("#publicCatalogCard").screenshot({ path: `${evidence}/preview-${width}.png`, animations: "disabled" });

    await select("#catalogPublishBtn").click();
    await status("#catalogPublishStatus", "Katalog publik telah terbit.");
    const publicUrl = await select("#catalogPublicLink").evaluate(link => link.href);
    const publicPage = await anonymous.newPage();
    publicPage.on("pageerror", error => errors.push(error.message));
    const published = await publicPage.goto(publicUrl);
    assert.equal(published.status(), 200);
    assert.equal(published.headers()["cache-control"], cachePolicy);
    const headers = await published.request().allHeaders();
    assert(!headers.cookie && !headers.authorization);
    assert.deepEqual(await anonymous.cookies(), []);
    assert.equal(await publicPage.getByRole("listitem").count(), 1);
    await publicPage.getByRole("heading", { name: "Bakso Urat" }).waitFor();
    const image = publicPage.getByRole("img");
    await image.evaluate(img => img.decode());
    await noOverflow(publicPage);
    await publicPage.screenshot({ path: `${evidence}/public-${width}.png`, fullPage: true, animations: "disabled" });

    await page.bringToFront();
    await select("#catalogCopyLinkBtn").click();
    await status("#catalogPublishStatus", "URL publik disalin.");
    assert.equal(await page.evaluate(() => navigator.clipboard.readText()), publicUrl);

    // A saved selection change must leave the active link unchanged.
    await select("#catalogChoices label").filter({ hasText: "Beras" }).locator("input").check();
    await select("#catalogPreviewBtn").click();
    await status("#catalogPublishStatus", "Pratinjau siap ditinjau.");
    await preview.getByRole("heading", { name: /Beras/ }).waitFor();
    assert.equal(await (await publicPage.reload()).status(), 200);
    assert.equal(await publicPage.getByRole("listitem").count(), 1);

    await select("#posterSampleBtn").click();
    await select("#posterCopyCaptionBtn").click();
    await status("#posterCopyStatus", "Caption disalin.");
    assert.equal(await page.evaluate(() => navigator.clipboard.readText()), await select("#posterCaption").innerText());
    for (const format of ["svg", "png"]) {
      await select("#posterFormat").selectOption(format);
      await select("#posterPreviewBtn").click();
      await status("#posterStatus", "Pratinjau siap diunduh.");
      const [download] = await Promise.all([
        page.waitForEvent("download"),
        select("#posterExportBtn").click()
      ]);
      assert(download.suggestedFilename().endsWith("." + format));
      const expected = await select("#posterPreviewImage").getAttribute("src");
      const bytes = await fs.readFile(await download.path());
      assert.deepEqual(bytes, Buffer.from(expected.split(",")[1], "base64"));
    }

    page.once("dialog", dialog => dialog.accept());
    await select("#catalogUnpublishBtn").click();
    await status("#catalogPublishStatus", "Publikasi ditarik.");
    const revoked = await publicPage.reload();
    assert.equal(revoked.status(), 404);
    assert.equal(revoked.headers()["cache-control"], cachePolicy);
    assert(await select("#catalogPublicLink").isHidden());
    assert.deepEqual(errors, []);
    console.log(`PASS ${width}px preview, publish, anonymous access, clipboard, SVG/PNG, draft isolation and revocation`);
  } finally {
    await browser.close();
  }
}

run().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
