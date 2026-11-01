import { type APIRequestContext, expect, test } from "@playwright/test";

import { DEMO_PASSWORD, signIn } from "./helpers";

const API_URL = process.env.ATLAS_E2E_API_URL ?? "http://localhost:8000";

/** Three cash deposits of US$9,000-9,500 into a seeded open USD account: structuring under
 * the US$10,000 reporting threshold. Returns the account number. */
async function structure(request: APIRequestContext): Promise<string> {
  const login = await request.post(`${API_URL}/api/v1/auth/login`, { data: { username: "employee", password: DEMO_PASSWORD } });
  const { access_token: token } = (await login.json()) as { access_token: string };
  const headers = { Authorization: `Bearer ${token}` };
  const response = await request.get(`${API_URL}/api/v1/accounts?status=open&limit=100`, { headers });
  const { items } = (await response.json()) as { items: { id: string; account_number: string; currency: string }[] };
  const account = items.find((a) => a.currency === "USD");
  if (!account) throw new Error("No seeded open USD account.");
  for (const [n, amount] of [900_000, 950_000, 920_000].entries()) {
    const made = await request.post(`${API_URL}/api/v1/accounts/${account.id}/deposits`, {
      headers: { ...headers, "Idempotency-Key": `e2e-aml-${account.id}-${n}-${Date.now()}` },
      data: { amount, memo: "Cash" },
    });
    expect(made.status()).toBe(201);
  }
  return account.account_number;
}

test("Compliance: structuring is detected, investigated, escalated and filed by a second officer", async ({ browser, page, request }) => {
  const accountNumber = await structure(request);
  await signIn(page, "compliance", "/compliance");
  const run = page.getByRole("form", { name: "Run monitoring" });
  await run.getByRole("button", { name: "Run monitoring" }).click();
  await page.getByLabel("Alerts for account").fill(accountNumber);
  const row = page.getByRole("table", { name: "Alerts" }).getByRole("row").filter({ hasText: accountNumber }).filter({ hasText: "Structuring" });
  await expect(row).toBeVisible();
  const alertNumber = (await row.locator("td").first().innerText()).trim();
  await page.getByRole("button", { name: `Investigate ${alertNumber}` }).click();
  const caseRow = page.getByRole("table", { name: "Cases" }).getByRole("row").filter({ hasText: alertNumber });
  await expect(caseRow.getByText("Investigating")).toBeVisible();
  const caseNumber = (await caseRow.locator("td").first().innerText()).trim();
  await page.getByRole("button", { name: `Escalate ${caseNumber}` }).click();
  const sarRow = page.getByRole("table", { name: "Suspicious activity reports" }).getByRole("row").filter({ hasText: caseNumber });
  await expect(sarRow.getByText("draft")).toBeVisible();
  const sarNumber = (await sarRow.locator("td").first().innerText()).trim();
  // The preparer cannot file it.
  await page.getByRole("button", { name: `File ${sarNumber}` }).click();
  await expect(page.getByText(/Four-eyes rule/)).toBeVisible();

  const otherContext = await browser.newContext();
  const other = await otherContext.newPage();
  await signIn(other, "admin", "/compliance");
  await other.getByRole("button", { name: `File ${sarNumber}` }).click();
  const filed = other.getByRole("table", { name: "Suspicious activity reports" }).getByRole("row").filter({ hasText: sarNumber });
  await expect(filed).toContainText("FIU-");
  await otherContext.close();
});
