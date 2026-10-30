import { expect, test } from "@playwright/test";

import { signIn } from "./helpers";

test("Countries: the 120-country reference data — Saudi Arabia's weekend, calendar and formats", async ({ page }) => {
  await signIn(page, "employee", "/countries");
  await expect(page.getByText("120 configured · target 120")).toBeVisible();

  await page.getByLabel("Region", { exact: true }).selectOption("middle_east_africa");
  await page.getByLabel("Status", { exact: true }).selectOption("planned");
  await page.getByLabel("Search countries").fill("Saudi");
  await page.getByRole("button", { name: "Saudi Arabia" }).click();

  const dialog = page.getByRole("dialog", { name: "Saudi Arabia (SA)" });
  await expect(dialog.getByText("Saudi Central Bank (SAMA)")).toBeVisible();
  await expect(dialog.getByText("Friday and Saturday")).toBeVisible();
  await expect(dialog.getByText("SAR · Saudi riyal, 2 decimals")).toBeVisible();
  const holidays = dialog.getByRole("region", { name: "Holiday calendar" });
  await expect(holidays.getByText("Founding Day")).toBeVisible();
  // Lunar holidays are dated from Phase 26: four days of Eid al-Fitr from 20 March 2026.
  await expect(holidays.getByText("Eid al-Fitr (day 4)")).toBeVisible();
  await expect(holidays.getByRole("status")).toHaveText("254 business days");

  const check = dialog.getByRole("region", { name: "Check a value" });
  await check.getByLabel("Value").fill("12345");
  await check.getByRole("button", { name: "Check" }).click();
  await expect(check.getByRole("status")).toHaveText("12345 matches the format");
  await expect(dialog.getByRole("region", { name: "Synthetic samples" }).getByRole("listitem")).toHaveCount(3);
});

test("Country rules: an administrator adds a version of Kuwait's rules", async ({ page }) => {
  await signIn(page, "admin", "/countries");
  await page.getByLabel("Search countries").fill("Kuwait");
  await page.getByRole("button", { name: "Kuwait" }).click();
  const rules = page.getByRole("dialog", { name: "Kuwait (KW)" }).getByRole("region", { name: "Country rules" });
  await expect(rules.getByText(/Age 21\+ · passport or national ID/)).toBeVisible();
  await expect(rules.getByText(/high value from 3,100 · limit 310,000 KWD/)).toBeVisible();

  const reason = `Synthetic change ${Date.now()}`;
  await rules.getByRole("button", { name: "New version" }).click();
  const form = rules.getByRole("form", { name: "New rules version" });
  await form.getByLabel("High-value threshold").fill("2500");
  await form.getByLabel("Effective from").fill("2099-01-01");
  await form.getByLabel("Reason").fill(reason);
  await form.getByRole("button", { name: "Save as a new version" }).click();
  await expect(rules.getByRole("list", { name: "Rule versions" })).toContainText(`from 2099-01-01: ${reason}`);
  // Not in force yet: today's rules are unchanged.
  await expect(rules.getByText(/high value from 3,100/)).toBeVisible();
});
