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
  await expect(holidays.getByRole("status")).toHaveText("259 business days");

  const check = dialog.getByRole("region", { name: "Check a value" });
  await check.getByLabel("Value").fill("12345");
  await check.getByRole("button", { name: "Check" }).click();
  await expect(check.getByRole("status")).toHaveText("12345 matches the format");
  await expect(dialog.getByRole("region", { name: "Synthetic samples" }).getByRole("listitem")).toHaveCount(3);
});
