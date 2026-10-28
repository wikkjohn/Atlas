import { expect, type Page } from "@playwright/test";

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
