import { type APIRequestContext, expect, type Page, test } from "@playwright/test";

import { DEMO_PASSWORD, signIn, uniqueWord } from "./helpers";

const API_URL = process.env.ATLAS_E2E_API_URL ?? "http://localhost:8000";

async function freshTeller(request: APIRequestContext): Promise<string> {
  const login = await request.post(`${API_URL}/api/v1/auth/login`, { data: { username: "admin", password: DEMO_PASSWORD } });
  const { access_token: token } = (await login.json()) as { access_token: string };
  const username = `teller.${uniqueWord()}`;
  const created = await request.post(`${API_URL}/api/v1/users`, {
    headers: { Authorization: `Bearer ${token}` },
    data: { username, email: `${username}@atlasbank.example`, display_name: `Teller ${username}`, password: DEMO_PASSWORD, role: "banking_employee" },
  });
  expect(created.status()).toBe(201);
  return username;
}

async function tryPassword(page: Page, username: string, password: string) {
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
}

test("Governance: five wrong passwords lock a teller out until an administrator unlocks them", async ({ browser, request }) => {
  const username = await freshTeller(request);
  const teller = await (await browser.newContext()).newPage();
  await teller.goto("/");
  for (let attempt = 0; attempt < 5; attempt++) {
    await tryPassword(teller, username, "not-the-password");
    await expect(teller.getByRole("alert")).toHaveText("Invalid username or password.");
  }
  // Locked: even the right password is refused, and the page says why.
  await tryPassword(teller, username, DEMO_PASSWORD);
  await expect(teller.getByRole("alert")).toContainText("locked after repeated failed sign-ins");

  const admin = await (await browser.newContext()).newPage();
  await signIn(admin, "admin", "/settings");
  await admin.getByLabel("Search users").fill(username);
  const users = admin.getByRole("table", { name: "Users" });
  await expect(users.getByText(/Locked until/)).toBeVisible();
  await users.getByRole("button", { name: `Unlock ${username}` }).click();
  await expect(users.getByText(/Locked until/)).toHaveCount(0);

  await tryPassword(teller, username, DEMO_PASSWORD);
  await expect(teller.getByRole("button", { name: "Sign out", exact: true })).toBeVisible();
});

test("Governance: the retention schedule is reviewed and applied, and the audit archive is verifiable", async ({ page }) => {
  await signIn(page, "admin", "/settings");
  const schedule = page.getByRole("table", { name: "Retention schedule" });
  await expect(schedule.getByText("Sign-in sessions").locator("xpath=ancestor::tr")).toContainText("90 days after the session ended");
  await expect(schedule.getByText("Customers").locator("xpath=ancestor::tr")).toContainText("Keep");
  await page.getByRole("button", { name: "Apply the retention schedule" }).click();
  await expect(page.getByText(/^Run #\d+: auth_sessions: \d+ deleted/)).toBeVisible();

  // Every event of a fresh database is recent: nothing is old enough to archive yet.
  await page.goto("/audit");
  await page.getByLabel("Archive events older than (days)").fill("400");
  await page.getByRole("button", { name: "Archive", exact: true }).click();
  await expect(page.getByRole("status")).toHaveText(/No events are that old\.|Archive #\d+/);
});
