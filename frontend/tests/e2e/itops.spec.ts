import { type Browser, expect, type Page, test } from "@playwright/test";

import { signIn } from "./helpers";

async function as(browser: Browser, username: string): Promise<Page> {
  const page = await (await browser.newContext()).newPage();
  await signIn(page, username, "/it-operations");
  return page;
}

const row = (page: Page, table: string, text: string) => page.getByRole("table", { name: table }).getByRole("row").filter({ hasText: text });

test("IT Operations: a P1 is acknowledged, resolved and closed with a review by someone else", async ({ browser }) => {
  const engineer = await as(browser, "employee");
  const report = engineer.getByRole("form", { name: "Report incident" });
  await report.getByLabel("Incident application").selectOption({ label: "Payments Gateway (tier 1)" });
  await report.getByLabel("What is wrong").fill("Payments are timing out");
  await report.getByLabel("Impact").selectOption("high");
  await report.getByLabel("Urgency").selectOption("high");
  await report.getByRole("button", { name: "Report incident" }).click();
  await expect(report.getByRole("status")).toContainText("P1");
  const incident = (await report.getByRole("status").innerText()).split(" ")[0];
  await engineer.getByRole("button", { name: `Acknowledge ${incident}` }).click();
  await expect(row(engineer, "Incidents", incident)).toContainText("acknowledged");
  await engineer.getByLabel(`Resolution for ${incident}`).fill("Raised the connection pool size.");
  await engineer.getByRole("button", { name: `Resolve ${incident}` }).click();
  await expect(row(engineer, "Incidents", incident)).toContainText("resolved");

  const manager = await as(browser, "manager");
  // A P1 needs a post-incident review to close.
  await manager.getByRole("button", { name: `Close ${incident}` }).click();
  await expect(manager.getByText(/post-incident review/).last()).toBeVisible();
  await manager.getByLabel(`Review for ${incident}`).fill("Root cause: the pool was sized for last year's volumes.");
  await manager.getByRole("button", { name: `Close ${incident}` }).click();
  await expect(row(manager, "Incidents", incident)).toContainText("closed");
});

test("IT Operations: a change is approved by someone else, fails and opens an incident", async ({ browser }) => {
  const engineer = await as(browser, "employee");
  const form = engineer.getByRole("form", { name: "Raise change" });
  await form.getByLabel("Change application").selectOption({ label: "Loan Origination (tier 2)" });
  await form.getByLabel("What changes").fill(`Patch the loan desk ${Date.now()}`);
  await form.getByLabel("Backout plan").fill("Roll back the patch.");
  await form.getByRole("button", { name: "Raise change" }).click();
  await expect(form.getByRole("status")).toContainText("requested: medium risk");
  const change = (await form.getByRole("status").innerText()).split(" ")[0];
  // The requester cannot approve it.
  await expect(engineer.getByRole("button", { name: `Approve ${change}` })).toHaveCount(0);

  const manager = await as(browser, "manager");
  await manager.getByRole("button", { name: `Approve ${change}` }).click();
  await expect(row(manager, "Changes", change)).toContainText("approved");

  await engineer.reload();
  await engineer.getByRole("button", { name: `Failed ${change}` }).click();
  await expect(row(engineer, "Changes", change)).toContainText("failed");
  await expect(row(engineer, "Incidents", `Failed change ${change}`)).toContainText(`caused by ${change}`);
});

test("AI Innovation Lab: the change assistant would approve another change after three failures (its blind spot)", async ({ page }) => {
  // The tool reads IT operations data (itops:read); the administrator has it.
  await signIn(page, "admin", "/ai-lab");
  const registry = page.getByRole("list", { name: "AI tools" });
  await registry.getByRole("button", { name: /AGB Change Review Assistant/ }).click();
  const details = page.getByRole("region", { name: "Tool details" });
  await expect(details.getByRole("heading", { name: "AGB Change Review Assistant" })).toBeVisible();
  const console = details.getByRole("form", { name: "Test console" });
  await console.getByLabel("Action").selectOption("recommend_decision");
  await console.getByRole("button", { name: "Invoke" }).click();
  await expect(console.getByRole("status")).toContainText("Recommendation: Approve");
});

test("IT Operations: the registry shows what the Core Banking Ledger relies on and what stops if it stops", async ({ page }) => {
  await signIn(page, "manager", "/it-operations");
  await expect(page.getByLabel("Estate summary")).toContainText("dependencies");
  await page.getByLabel("Search applications").fill("Core Banking Ledger");
  const table = page.getByRole("table", { name: "Applications" });
  await expect(table.getByRole("row")).toHaveCount(1);
  await table.getByRole("button", { name: /^Show APP-/ }).click();
  const detail = page.getByRole("region", { name: "Application detail" });
  await expect(detail).toContainText("Core Banking Ledger");
  // Payments Gateway, Card Authorisation, Online Banking and others call the ledger.
  await expect(detail.getByRole("list", { name: "Relied on by" })).toContainText("Payments Gateway · api");
  await expect(detail.getByLabel("If it stops")).toContainText("applications affected");
});
