// Run only against a local test instance: creates one synthetic investigation.
const { chromium } = require("playwright");
const assert = require("node:assert/strict");

const web = process.env.TEST_WEB_URL || "http://localhost:3000";
const api = process.env.TEST_API_URL || "http://localhost:8000";
for (const address of [web, api]) {
  const url = new URL(address);
  assert.ok(["localhost", "127.0.0.1"].includes(url.hostname), "Use a local test instance");
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage();
    const errors = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.goto(web);
    await page.locator("select").first().selectOption("company");
    await page.getByLabel(/Navn eller identifikator/).fill("Syntetisk nettlesertest AS");
    await page.getByLabel(/Hva skal undersøkelsen avklare/).fill("Kontroll av lagring og scope i lokal test.");
    await page.getByRole("checkbox", { name: /BUSINESS ROLES/ }).check();
    await page.getByRole("button", { name: /Opprett undersøkelse/ }).click();
    await page.waitForURL("**/investigations/*");
    const heading = page.getByRole("heading", { name: "Syntetisk nettlesertest AS", exact: true });
    await heading.waitFor();
    await page.reload();
    await heading.waitFor();

    const id = page.url().split("/").pop();
    const response = await fetch(`${api}/api/v1/investigations/${id}`);
    assert.equal(response.status, 200);
    const body = await response.json();
    assert.deepEqual(body.scope_modules, ["BUSINESS_ROLES"]);
    assert.equal(body.modules.filter(module => module.enabled).length, 1);
    const rows = page.locator(".coverage-row");
    assert.match(await rows.filter({ hasText: "FINANCIALS" }).innerText(), /Ikke valgt/);
    assert.match(await rows.filter({ hasText: "BUSINESS ROLES" }).innerText(), /Ikke undersøkt ennå/);

    await page.getByRole("link", { name: /Dekningsrapport/ }).click();
    await page.waitForURL("**/report");
    await page.getByRole("heading", { name: "Dekningsrapport", exact: true }).waitFor();
    await page.getByRole("heading", { name: /Ikke valgt \(8\)/ }).waitFor();
    await page.getByRole("heading", { name: /Ikke undersøkt \(1\)/ }).waitFor();
    const reportText = await page.locator("main").innerText();
    assert.match(reportText, /BUSINESS ROLES/);
    assert.match(reportText, /FINANCIALS/);
    assert.match(reportText, /Områder du ikke valgte/);
    assert.deepEqual(errors, []);
    console.log(`PASS: create, detail, reload, scope display and report. Synthetic investigation: ${id}`);
  } finally {
    await browser.close();
  }
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
