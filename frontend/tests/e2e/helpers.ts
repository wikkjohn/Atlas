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

/** A seeded open current account holding at least `minimum` minor units with room for another
 * card (at most two live cards an account), so card tests leave other accounts alone. */
export async function cardAccount(request: APIRequestContext, minimum: number): Promise<string> {
  const login = await request.post(`${API_URL}/api/v1/auth/login`, {
    data: { username: "admin", password: DEMO_PASSWORD },
  });
  const { access_token: token } = (await login.json()) as { access_token: string };
  const headers = { Authorization: `Bearer ${token}` };
  const accounts = await request.get(`${API_URL}/api/v1/accounts?status=open&account_type=current&limit=100`, { headers });
  const { items } = (await accounts.json()) as { items: { id: string; account_number: string; balance: number }[] };
  for (const account of items.filter((a) => a.balance >= minimum)) {
    const cards = await request.get(`${API_URL}/api/v1/cards?account_id=${account.id}`, { headers });
    const { items: issued } = (await cards.json()) as { items: { status: string }[] };
    if (issued.filter((c) => c.status !== "cancelled").length < 2) return account.account_number;
  }
  throw new Error(`No seeded current account holds ${minimum} minor units with room for a card.`);
}

/** A seeded customer the synthetic bureau scores well, with an open current account in GBP,
 * EUR or USD and a newly registered, surveyor-valued house: what a mortgage needs. Found by
 * asking the quote API, so the rules decide (Phase 33). */
export async function mortgageApplicant(request: APIRequestContext): Promise<{
  customerNumber: string;
  propertyNumber: string;
  accountNumber: string;
  loan: string;
  income: string;
}> {
  const login = await request.post(`${API_URL}/api/v1/auth/login`, {
    data: { username: "manager", password: DEMO_PASSWORD },
  });
  const { access_token: token } = (await login.json()) as { access_token: string };
  const headers = { Authorization: `Bearer ${token}` };
  const response = await request.get(`${API_URL}/api/v1/accounts?status=open&account_type=current&limit=100`, { headers });
  const { items } = (await response.json()) as { items: { account_number: string; customer_number: string; currency: string }[] };
  const price = 30_000_000; // 300,000.00
  for (const account of items.filter((a) => ["GBP", "EUR", "USD"].includes(a.currency))) {
    const body = {
      customer_number: account.customer_number,
      product_code: "home-75",
      account_number: account.account_number,
      loan_amount: price / 5,
      term_years: 25,
    };
    const created = await request.post(`${API_URL}/api/v1/mortgages/properties`, {
      headers,
      data: { customer_number: account.customer_number, property_type: "house", purchase_price: price },
    });
    if (!created.ok()) continue;
    const property = (await created.json()) as { id: string; property_number: string; currency: string };
    if (property.currency !== account.currency) continue;
    await request.post(`${API_URL}/api/v1/mortgages/properties/${property.id}/valuations`, {
      headers,
      data: { method: "surveyor", value: price },
    });
    const quoted = await request.post(`${API_URL}/api/v1/mortgages/quote`, {
      headers,
      data: { ...body, property_number: property.property_number, declared_monthly_income: 0 },
    });
    const quote = (await quoted.json()) as { income_estimate: number; checks: { rule: string; passed: boolean }[] };
    const failed = quote.checks.filter((c) => !c.passed).map((c) => c.rule);
    // Declared income 0 fails affordability only; declaring the bureau's estimate passes it.
    if (failed.length === 1 && failed[0] === "affordability") {
      return {
        customerNumber: account.customer_number,
        propertyNumber: property.property_number,
        accountNumber: account.account_number,
        loan: String(price / 5 / 100),
        income: String(quote.income_estimate / 100),
      };
    }
  }
  throw new Error("No seeded customer qualifies for a mortgage.");
}
