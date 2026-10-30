import { type APIRequestContext, expect, type Page } from "@playwright/test";

export const DEMO_PASSWORD = process.env.ATLAS_DEMO_PASSWORD ?? "atlas-demo-password";

export async function signIn(page: Page, username: string, path = "/"): Promise<void> {
  await page.goto(path);
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Password").fill(DEMO_PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
}

export function nav(page: Page) {
  return page.getByRole("navigation", { name: "Primary" });
}

/** A letters-only suffix (names may not contain digits) that is unique per run. */
export function uniqueWord(): string {
  return Array.from({ length: 6 }, () =>
    String.fromCharCode(97 + Math.floor(Math.random() * 26)),
  ).join("");
}

const API_URL = process.env.ATLAS_E2E_API_URL ?? "http://localhost:8000";

/** A seeded open account with at least `minimum` minor units, and its customer (read through
 * the API as `username`). Watchlisted names are skipped: screening would route them aside. */
export async function fundedAccount(
  request: APIRequestContext,
  minimum: number,
  username = "admin",
): Promise<{ accountNumber: string; customerNumber: string; customerName: string }> {
  const login = await request.post(`${API_URL}/api/v1/auth/login`, {
    data: { username, password: DEMO_PASSWORD },
  });
  const { access_token: token } = (await login.json()) as { access_token: string };
  const response = await request.get(`${API_URL}/api/v1/accounts?status=open&limit=100`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  const { items } = (await response.json()) as {
    items: { account_number: string; customer_number: string; customer_name: string; balance: number }[];
  };
  const listed = /vantablack|ledgerworth|offshore|shellcompany/i;
  const account = items.find((a) => a.balance >= minimum && !listed.test(a.customer_name));
  if (!account) throw new Error(`No seeded open account holds ${minimum} minor units.`);
  return { accountNumber: account.account_number, customerNumber: account.customer_number, customerName: account.customer_name };
}
