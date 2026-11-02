import { expect } from "@playwright/test";
export const DEMO_PASSWORD = process.env.ATLAS_DEMO_PASSWORD ?? "atlas-demo-password";
export async function signIn(page, username, path = "/") {
    await page.goto(path);
    await page.getByLabel("Username").fill(username);
    await page.getByLabel("Password").fill(DEMO_PASSWORD);
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
}
export function nav(page) {
    return page.getByRole("navigation", { name: "Primary" });
}
/** A letters-only suffix (names may not contain digits) that is unique per run. */
export function uniqueWord() {
    return Array.from({ length: 6 }, () => String.fromCharCode(97 + Math.floor(Math.random() * 26))).join("");
}
const API_URL = process.env.ATLAS_E2E_API_URL ?? "http://localhost:8000";
/** A seeded open account with at least `minimum` minor units, and its customer (read through
 * the API as `username`). Watchlisted names are skipped: screening would route them aside. */
export async function fundedAccount(request, minimum, username = "admin") {
    const login = await request.post(`${API_URL}/api/v1/auth/login`, {
        data: { username, password: DEMO_PASSWORD },
    });
    const { access_token: token } = (await login.json());
    const response = await request.get(`${API_URL}/api/v1/accounts?status=open&limit=100`, {
        headers: { Authorization: `Bearer ${token}` },
    });
    const { items } = (await response.json());
    const listed = /vantablack|ledgerworth|offshore|shellcompany/i;
    const account = items.find((a) => a.balance >= minimum && !listed.test(a.customer_name));
    if (!account)
        throw new Error(`No seeded open account holds ${minimum} minor units.`);
    return { accountNumber: account.account_number, customerNumber: account.customer_number, customerName: account.customer_name };
}
/** A seeded open current account holding at least `minimum` minor units with room for another
 * card (at most two live cards an account), so card tests leave other accounts alone. */
export async function cardAccount(request, minimum) {
    const login = await request.post(`${API_URL}/api/v1/auth/login`, {
        data: { username: "admin", password: DEMO_PASSWORD },
    });
    const { access_token: token } = (await login.json());
    const headers = { Authorization: `Bearer ${token}` };
    const accounts = await request.get(`${API_URL}/api/v1/accounts?status=open&account_type=current&limit=100`, { headers });
    const { items } = (await accounts.json());
    for (const account of items.filter((a) => a.balance >= minimum)) {
        const cards = await request.get(`${API_URL}/api/v1/cards?account_id=${account.id}`, { headers });
        const { items: issued } = (await cards.json());
        if (issued.filter((c) => c.status !== "cancelled").length < 2)
            return account.account_number;
    }
    throw new Error(`No seeded current account holds ${minimum} minor units with room for a card.`);
}
/** A seeded customer the synthetic bureau scores well, with an open current account in GBP,
 * EUR or USD and a newly registered, surveyor-valued house: what a mortgage needs. Found by
 * asking the quote API, so the rules decide (Phase 33). */
export async function mortgageApplicant(request) {
    const login = await request.post(`${API_URL}/api/v1/auth/login`, {
        data: { username: "manager", password: DEMO_PASSWORD },
    });
    const { access_token: token } = (await login.json());
    const headers = { Authorization: `Bearer ${token}` };
    const response = await request.get(`${API_URL}/api/v1/accounts?status=open&account_type=current&limit=100`, { headers });
    const { items } = (await response.json());
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
        if (!created.ok())
            continue;
        const property = (await created.json());
        if (property.currency !== account.currency)
            continue;
        await request.post(`${API_URL}/api/v1/mortgages/properties/${property.id}/valuations`, {
            headers,
            data: { method: "surveyor", value: price },
        });
        const quoted = await request.post(`${API_URL}/api/v1/mortgages/quote`, {
            headers,
            data: { ...body, property_number: property.property_number, declared_monthly_income: 0 },
        });
        const quote = (await quoted.json());
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
/** A seeded verified business with an open business current account in GBP, EUR or USD
 * (Phase 35). */
export async function businessAccount(request) {
    const login = await request.post(`${API_URL}/api/v1/auth/login`, {
        data: { username: "admin", password: DEMO_PASSWORD },
    });
    const { access_token: token } = (await login.json());
    const response = await request.get(`${API_URL}/api/v1/accounts?status=open&account_type=business_current&limit=100`, {
        headers: { Authorization: `Bearer ${token}` },
    });
    const { items } = (await response.json());
    const account = items.find((a) => ["GBP", "EUR", "USD"].includes(a.currency));
    if (!account)
        throw new Error("No seeded business current account in GBP, EUR or USD.");
    return { customerNumber: account.customer_number, accountNumber: account.account_number };
}
