import { type APIRequestContext, expect, test } from "@playwright/test";

import { DEMO_PASSWORD, signIn } from "./helpers";

const API_URL = process.env.ATLAS_E2E_API_URL ?? "http://localhost:8000";

/** A seeded open USD account and its customer number. */
async function seededAccount(request: APIRequestContext): Promise<{ account: string; customer: string }> {
  const login = await request.post(`${API_URL}/api/v1/auth/login`, { data: { username: "employee", password: DEMO_PASSWORD } });
  const { access_token: token } = (await login.json()) as { access_token: string };
  const headers = { Authorization: `Bearer ${token}` };
  const accounts = await request.get(`${API_URL}/api/v1/accounts?status=open&limit=100`, { headers });
  const { items } = (await accounts.json()) as { items: { account_number: string; customer_id: string; currency: string }[] };
  const account = items.find((a) => a.currency === "USD");
  if (!account) throw new Error("No seeded open USD account.");
  const customer = await request.get(`${API_URL}/api/v1/customers/${account.customer_id}`, { headers });
  const { customer_number } = (await customer.json()) as { customer_number: string };
  return { account: account.account_number, customer: customer_number };
}

test("Customer Service: a teller opens a complaint and proposes redress; a manager pays it and the complaint is upheld", async ({ browser, page, request }) => {
  const { account, customer } = await seededAccount(request);
  await signIn(page, "employee", "/customer-service");
  const form = page.getByRole("form", { name: "Open case" });
  await form.getByLabel("Customer number").fill(customer);
  await form.getByLabel("Account number").fill(account);
  await form.getByLabel("Category").selectOption("complaint");
  await form.getByLabel("Topic").selectOption("fees");
  await form.getByLabel("Subject").fill("Monthly fee charged twice");
  await form.getByLabel("Description").fill("The October fee was taken twice.");
  await form.getByRole("button", { name: "Open case" }).click();
  const status = form.getByRole("status");
  await expect(status).toContainText("opened");
  const caseNumber = (await status.innerText()).split(" ")[0];
  await page.getByRole("button", { name: `Respond to ${caseNumber}` }).click();
  await expect(page.getByRole("button", { name: `Respond to ${caseNumber}` })).toHaveCount(0);
  await page.getByLabel(`Redress for ${caseNumber}`).fill("15");
  await page.getByRole("button", { name: `Propose redress on ${caseNumber}` }).click();
  const row = page.getByRole("table", { name: "Cases" }).getByRole("row").filter({ hasText: caseNumber });
  await expect(row).toContainText("Redress $15.00 proposed");
  // Paying needs service:approve, which tellers do not have.
  await expect(page.getByRole("button", { name: `Pay redress on ${caseNumber}` })).toHaveCount(0);

  const otherContext = await browser.newContext();
  const other = await otherContext.newPage();
  await signIn(other, "manager", "/customer-service");
  await other.getByRole("button", { name: `Pay redress on ${caseNumber}` }).click();
  const paid = other.getByRole("table", { name: "Cases" }).getByRole("row").filter({ hasText: caseNumber });
  await expect(paid).toContainText("Redress $15.00 paid (JE-");
  await other.getByRole("button", { name: `Resolve ${caseNumber}` }).click();
  await other.getByLabel("Case status").selectOption("resolved");
  await expect(other.getByRole("table", { name: "Cases" }).getByRole("row").filter({ hasText: caseNumber })).toContainText("Upheld");
  await otherContext.close();
});
