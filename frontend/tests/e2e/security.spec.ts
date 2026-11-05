import { createHmac } from "node:crypto";

import { type APIRequestContext, expect, type Page, test } from "@playwright/test";

import { DEMO_PASSWORD, signIn, uniqueWord } from "./helpers";

const API_URL = process.env.ATLAS_E2E_API_URL ?? "http://localhost:8000";

async function token(request: APIRequestContext, username: string): Promise<string> {
  const login = await request.post(`${API_URL}/api/v1/auth/login`, { data: { username, password: DEMO_PASSWORD } });
  return ((await login.json()) as { access_token: string }).access_token;
}

/** A fresh teller, so enrolling a factor or setting a scope leaves the demo users alone. */
async function freshTeller(request: APIRequestContext): Promise<string> {
  const username = `teller.${uniqueWord()}`;
  const created = await request.post(`${API_URL}/api/v1/users`, {
    headers: { Authorization: `Bearer ${await token(request, "admin")}` },
    data: { username, email: `${username}@atlasbank.example`, display_name: `Teller ${username}`, password: DEMO_PASSWORD, role: "banking_employee" },
  });
  expect(created.status()).toBe(201);
  return username;
}

/** RFC 6238 in Node, as an authenticator app would compute it. */
function totp(secret: string, step = Math.floor(Date.now() / 30_000)): string {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let bits = "";
  for (const char of secret) bits += alphabet.indexOf(char).toString(2).padStart(5, "0");
  const key = Buffer.from(bits.match(/.{8}/g)!.map((b) => parseInt(b, 2)));
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(step));
  const digest = createHmac("sha1", key).update(counter).digest();
  const offset = digest[digest.length - 1] & 0x0f;
  return String((digest.readUInt32BE(offset) & 0x7fffffff) % 1_000_000).padStart(6, "0");
}

async function passwordStep(page: Page, username: string) {
  await page.goto("/");
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Password").fill(DEMO_PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
}

test("Security: a teller enrols an authenticator, then signs in with a code and a recovery code", async ({ page, request }) => {
  const username = await freshTeller(request);
  await passwordStep(page, username);
  await page.getByRole("link", { name: "Security" }).click();
  await expect(page.getByRole("heading", { name: "Security" })).toBeVisible();
  await page.getByRole("button", { name: "Set up an authenticator" }).click();
  const secret = (await page.getByLabel("Secret").textContent())!.trim();
  // The page's simulated authenticator shows what an app would: the same code.
  const shown = page.getByTestId("authenticator-code");
  await expect(shown).toHaveText(/^\d{6}$/);
  expect([totp(secret), totp(secret, Math.floor(Date.now() / 30_000) - 1)]).toContain(await shown.textContent());
  await page.getByLabel("Code from the authenticator").fill((await shown.textContent())!);
  await page.getByRole("button", { name: "Turn on" }).click();
  const recovery = page.getByLabel("Recovery codes");
  await expect(recovery).toBeVisible();
  const firstRecovery = (await recovery.locator("li").first().textContent())!;
  await expect(page.getByText("8 recovery code(s) left.")).toBeVisible();
  await page.getByRole("button", { name: "Sign out", exact: true }).click();

  // Next sign-in asks for the factor. A code a step ahead is within the accepted drift and
  // never the one just used.
  await passwordStep(page, username);
  const second = page.getByRole("form", { name: "Second factor" });
  await second.getByLabel("Code").fill(totp(secret, Math.floor(Date.now() / 30_000) + 1));
  await second.getByRole("button", { name: "Verify" }).click();
  await expect(page.getByRole("button", { name: "Sign out", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Sign out", exact: true }).click();

  await passwordStep(page, username);
  await page.getByRole("form", { name: "Second factor" }).getByLabel("Code").fill(firstRecovery);
  await page.getByRole("button", { name: "Verify" }).click();
  await page.getByRole("link", { name: "Security" }).click();
  await expect(page.getByText("7 recovery code(s) left.")).toBeVisible();
  await expect(page.getByRole("table", { name: "Sessions" })).toContainText("Ended: signed out");
});

test("Security: single sign-on through the simulated corporate directory", async ({ page, request }) => {
  const username = await freshTeller(request);
  await page.goto("/");
  await page.getByRole("button", { name: "Continue with ATLAS Corporate Directory (simulated SSO)" }).click();
  const directory = page.getByRole("form", { name: "ATLAS Corporate Directory" });
  await directory.getByLabel("Directory username").fill(username);
  await directory.getByLabel("Directory password").fill(DEMO_PASSWORD);
  await directory.getByRole("button", { name: "Continue to ATLAS Global Bank" }).click();
  await expect(page.getByRole("button", { name: "Sign out", exact: true })).toBeVisible();
  await page.getByRole("link", { name: "Security" }).click();
  await expect(page.getByRole("table", { name: "Sessions" })).toContainText("SSO (atlas-directory)");
});

test("Security: an administrator limits a teller to Great Britain", async ({ page, request }) => {
  const username = await freshTeller(request);
  await signIn(page, "admin", "/settings");
  await page.getByLabel("Search users").fill(username);
  await page.getByRole("button", { name: `Access of ${username}` }).click();
  const dialog = page.getByRole("dialog", { name: `Access of ${username}` });
  await dialog.getByLabel("Countries (ISO codes, comma-separated)").fill("GB");
  await dialog.getByRole("button", { name: "Save scopes" }).click();
  await expect(dialog.getByRole("status")).toHaveText("Saved: GB; all departments.");

  // The teller now sees British customers only.
  const headers = { Authorization: `Bearer ${await token(request, username)}` };
  const customers = (await (await request.get(`${API_URL}/api/v1/customers?limit=200`, { headers })).json()) as {
    items: { country_code: string }[];
  };
  expect(customers.items.length).toBeGreaterThan(0);
  expect(new Set(customers.items.map((c) => c.country_code))).toEqual(new Set(["GB"]));
});
