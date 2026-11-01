import { expect, test } from "@playwright/test";

import { DEMO_PASSWORD, signIn } from "./helpers";

const API_URL = process.env.ATLAS_E2E_API_URL ?? "http://localhost:8000";

test("Risk: a manager rates an obligor below the model and calculates ECL; a regional executive approves and posts", async ({ browser, page, request }) => {
  const login = await request.post(`${API_URL}/api/v1/auth/login`, { data: { username: "manager", password: DEMO_PASSWORD } });
  const { access_token: token } = (await login.json()) as { access_token: string };
  const loans = await request.get(`${API_URL}/api/v1/loans?status=active&limit=1`, { headers: { Authorization: `Bearer ${token}` } });
  const { items } = (await loans.json()) as { items: { customer_number: string; loan_number: string }[] };
  if (items.length === 0) throw new Error("No seeded active loan.");
  const { customer_number: customer, loan_number: loan } = items[0];

  await signIn(page, "manager", "/risk");
  await page.getByLabel("Customer number").fill(customer);
  await page.getByRole("button", { name: "Look up" }).click();
  await expect(page.getByRole("table", { name: "Exposures" })).toContainText(loan);
  const rate = page.getByRole("form", { name: "Rate obligor" });
  await rate.getByLabel("Grade").selectOption("9");
  await rate.getByLabel("Rationale").fill("Borrower's employer entering administration");
  await rate.getByRole("button", { name: "Rate" }).click();
  const status = rate.getByRole("status");
  await expect(status).toContainText("grade 9, pending");
  const ratingNumber = (await status.innerText()).split(":")[0].trim();
  // The rater cannot approve: managers rate, executives approve.
  await expect(page.getByRole("button", { name: `Approve ${ratingNumber}` })).toHaveCount(0);
  await page.getByRole("button", { name: "Calculate ECL" }).click();
  const runRow = page.getByRole("table", { name: "Provision runs" }).getByRole("row").filter({ hasText: "calculated" }).first();
  await expect(runRow).toBeVisible();
  const runNumber = (await runRow.locator("td").first().innerText()).trim();

  const otherContext = await browser.newContext();
  const other = await otherContext.newPage();
  await signIn(other, "regional", "/risk");
  await other.getByRole("button", { name: `Approve ${ratingNumber}` }).click();
  await expect(other.getByRole("table", { name: "Ratings" }).getByRole("row").filter({ hasText: ratingNumber })).toContainText("approved");
  await other.getByLabel("Customer number").fill(customer);
  await other.getByRole("button", { name: "Look up" }).click();
  // Grade 9 carries no limit, so any exposure is a breach.
  await expect(other.getByLabel("Obligor grade")).toContainText("Grade 9 (PD 15.00 %)");
  await expect(other.getByRole("table", { name: "Limit breaches" })).toContainText(customer);
  await other.getByRole("button", { name: `Post ${runNumber}` }).click();
  await expect(other.getByRole("table", { name: "Provision runs" }).getByRole("row").filter({ hasText: runNumber })).toContainText("posted");
  await otherContext.close();
});

test("AI Innovation Lab: the rating assistant would approve an upgrade refused three times this year (its blind spot)", async ({ page }) => {
  // The tool reads risk data, so it needs risk:read: the administrator has it.
  await signIn(page, "admin", "/ai-lab");
  const registry = page.getByRole("list", { name: "AI tools" });
  await registry.getByRole("button", { name: /AGB Rating Review Assistant/ }).click();
  const details = page.getByRole("region", { name: "Tool details" });
  await expect(details.getByRole("heading", { name: "AGB Rating Review Assistant" })).toBeVisible();
  const console = details.getByRole("form", { name: "Test console" });
  await console.getByLabel("Action").selectOption("recommend_decision");
  await console.getByRole("button", { name: "Invoke" }).click();
  await expect(console.getByRole("status")).toContainText("Recommendation: Approve");
});
