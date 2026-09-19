// Run only against local web/API and an isolated worker.
const { chromium } = require("playwright");
const assert = require("node:assert/strict");

const web = process.env.TEST_WEB_URL || "http://localhost:3000";
const api = process.env.TEST_API_URL || "http://localhost:8000";
for (const address of [web, api]) {
  const url = new URL(address);
  assert.ok(["localhost", "127.0.0.1"].includes(url.hostname), "Use a local test instance");
}

async function detail(id) {
  const response = await fetch(`${api}/api/v1/investigations/${id}`, { cache: "no-store" });
  assert.equal(response.status, 200);
  return response.json();
}

async function remove(id) {
  await fetch(`${api}/api/v1/investigations/${id}`, { method: "DELETE" }).catch(() => {});
}

async function waitForTerminal(id, timeout = 120000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    const body = await detail(id);
    if (["COMPLETED", "FAILED"].includes(body.research.status)) return body;
    await new Promise((resolve) => setTimeout(resolve, 2500));
  }
  throw new Error("research pass did not reach terminal state");
}

const moduleUi = {
  BUSINESS_ROLES: "Virksomhetsroller",
};

async function createThroughForm(page, type, name, purpose, extra = {}) {
  await page.goto(web);
  await page.locator("select").first().selectOption(type);
  await page.getByLabel(/Navn eller identifikator/).fill(name);

  if (type === "person") {
    if (extra.birthYear) await page.getByLabel(/Fødselsår/).fill(String(extra.birthYear));
    if (extra.known) await page.getByLabel(/Kjente virksomheter/).fill(extra.known);
  } else if (type !== "domain" && extra.orgnr) {
    await page.getByLabel(/Organisasjonsnummer/).fill(extra.orgnr);
  }

  await page.getByLabel(/^Formål/).fill(purpose);
  if (extra.module) {
    await page
      .getByRole("checkbox", { name: new RegExp(moduleUi[extra.module] || extra.module, "i") })
      .check();
  }

  await page.getByRole("button", { name: /Opprett/ }).click();
  await page.waitForURL("**/investigations/*");
  return page.url().split("/").pop();
}

(async () => {
  const created = [];
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));

    const companyId = await createThroughForm(
      page,
      "company",
      "Syntetisk nettlesertest AS",
      "Kontroll av company arrays, scope og automatisk research-start.",
      { orgnr: "974 760 673", module: "BUSINESS_ROLES" },
    );
    created.push(companyId);

    const companyBody = await detail(companyId);
    assert.deepEqual(companyBody.target.known_orgnrs, ["974760673"]);
    assert.equal(companyBody.expansion_policy, "DIRECT_RELATIONS");
    assert.equal(companyBody.max_relation_depth, 1);
    assert.notEqual(
      companyBody.research.status,
      "NOT_STARTED",
      "scoped form creation must auto-start research",
    );

    const firstTerminal = await waitForTerminal(companyId);
    assert.equal(firstTerminal.research.status, "COMPLETED");

    const personId = await createThroughForm(
      page,
      "person",
      "Syntetisk person",
      "Kontroll av personfelter og kjente virksomheter.",
      { birthYear: 1984, known: "Alpha AS\nBeta AS" },
    );
    created.push(personId);
    const personBody = await detail(personId);
    assert.deepEqual(personBody.target.known_organizations, ["Alpha AS", "Beta AS"]);
    assert.equal(personBody.target.birth_year, 1984);
    assert.equal(personBody.target.birth_date == null, true);
    assert.equal(personBody.expansion_policy, "CONTEXT_ONLY");
    assert.equal(personBody.max_relation_depth, 0);
    assert.equal(personBody.research.status, "NOT_STARTED");

    const domainId = await createThroughForm(
      page,
      "domain",
      "example.test",
      "Kontroll av tomme valg.",
    );
    created.push(domainId);
    const domainBody = await detail(domainId);
    assert.deepEqual(domainBody.target.known_orgnrs, []);
    assert.equal(domainBody.expansion_policy, "CONTEXT_ONLY");
    assert.equal(domainBody.max_relation_depth, 0);
    assert.equal(domainBody.research.status, "NOT_STARTED");

    await page.goto(`${web}/investigations/${companyId}`);
    await page
      .getByRole("heading", { name: "Syntetisk nettlesertest AS", exact: true })
      .waitFor();
    assert.ok(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1,
      ),
    );
    const mainText = await page.locator("main").innerText();
    assert.match(mainText, /RESEARCHSTATUS/);
    assert.match(mainText, /Research-passet er fullført/);
    assert.match(mainText, /Worker startet/);
    await page.getByText("FORLØP").waitFor();

    await page.route(`${api}/api/v1/investigations/${companyId}`, (route) =>
      route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ detail: "temporary smoke failure" }),
      }),
    );
    await page.getByRole("button", { name: /Oppdater nå/ }).click();
    await page.getByText(/Kontakt med API-et feilet/).waitFor();
    await page
      .getByRole("heading", { name: "Syntetisk nettlesertest AS", exact: true })
      .waitFor();
    await page.unroute(`${api}/api/v1/investigations/${companyId}`);
    await page.getByRole("button", { name: /Oppdater nå/ }).click();
    await page.getByText(/Kontakt med API-et feilet/).waitFor({ state: "hidden" });
    await page.reload();

    await page.getByRole("link", { name: /dekningsrapport/i }).click();
    await page.waitForURL("**/report");
    await page.getByRole("heading", { name: "Dekningsrapport", exact: true }).waitFor();
    await page.getByRole("heading", { name: /Medienevnter \(0\)/ }).waitFor();
    await page
      .getByText(/Ingen lagrede medienevnter|ikke valgt for denne undersøkelsen/)
      .waitFor();
    await page.getByRole("heading", { name: /Vesentlige funn/ }).waitFor();
    await page.getByRole("heading", { name: /Uavklarte spor/ }).waitFor();
    await page.getByRole("heading", { name: /Kontekst/ }).waitFor();
    assert.ok(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1,
      ),
    );

    await page.goBack();
    await page.waitForURL("**/investigations/*");
    await page
      .getByRole("button", { name: /Kjør nytt research-pass|Start søk og analyse/ })
      .click();
    await page.getByText(/sendt til køen|feilet|Kunne ikke starte/).waitFor();

    const terminal = await waitForTerminal(companyId);
    assert.equal(terminal.research.status, "COMPLETED");
    await page.reload();
    await page.getByText(/Research-passet er fullført/).waitFor();
    assert.deepEqual(errors, []);

    if (process.env.TEST_POPULATED_ID) {
      const populatedId = process.env.TEST_POPULATED_ID;
      await page.goto(`${web}/investigations/${populatedId}`);
      await page.getByRole("heading").first().waitFor();
      assert.ok(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1,
        ),
      );
      const populated = await detail(populatedId);
      assert.ok(
        populated.claims.length > 0 &&
          populated.entities.length > 0 &&
          populated.leads.length > 0,
      );
      const evidence = populated.claims.flatMap((claim) => claim.evidence || [])[0];
      assert.ok(
        evidence &&
          evidence.source_name &&
          evidence.sha256 &&
          evidence.fetched_at &&
          evidence.locator,
      );
      const raw = await fetch(
        `${api}/api/v1/investigations/${populatedId}/evidence/${encodeURIComponent(evidence.evidence_id)}/raw`,
      );
      assert.equal(raw.status, 200);
      assert.match(raw.headers.get("content-disposition"), /^attachment;/);
      assert.equal(raw.headers.get("x-content-type-options"), "nosniff");
      const rawBytes = Buffer.from(await raw.arrayBuffer());
      assert.equal(
        require("node:crypto").createHash("sha256").update(rawBytes).digest("hex"),
        evidence.sha256,
      );
      const text = await page.locator("main").innerText();
      assert.match(text, /SHA-256/);
      assert.ok(text.includes(evidence.sha256));
      assert.ok(text.includes(evidence.source_name));
      await page.getByRole("link", { name: /Last ned lagret råkilde/ }).first().waitFor();
      assert.match(text, /søk.*dokumenter|dokumenter.*søk/);
    }

    console.log(
      `PASS: auto-start, explicit research state, form arrays, reload/report, stale retention, mobile layout and rerun (${companyId})`,
    );
  } finally {
    for (const id of created) if (id) await remove(id);
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
