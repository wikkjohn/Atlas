import { expect, test } from "@playwright/test";

import { signIn } from "./helpers";

test("Retail Banking: a manager sees the products and runs month end", async ({ page }) => {
  await signIn(page, "manager", "/retail");
  const products = page.getByRole("table", { name: "Retail products" });
  await expect(products.getByText("Everyday Current Account")).toBeVisible();
  await expect(products.getByText("19.90 %")).toBeVisible();
  await expect(products.getByText("2.50 %")).toBeVisible();

  await page.getByRole("button", { name: "Run month end" }).click();
  await expect(page.getByRole("status").filter({ hasText: /Job #\d+ queued/ })).toBeVisible();
  // The job runs in the API process; the run appears once it has finished.
  await page.reload();
  await expect(page.getByRole("table", { name: "Month-end runs" }).getByText(/\d+ accounts · \d+ postings/)).toBeVisible();
});

test("Retail Banking: a teller cannot change terms or run month end", async ({ page }) => {
  await signIn(page, "employee", "/retail");
  await expect(page.getByRole("table", { name: "Retail products" }).getByText("Instant Access Savings")).toBeVisible();
  await expect(page.getByRole("button", { name: /^Edit / })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Run month end" })).toHaveCount(0);
  await expect(page.getByRole("form", { name: "New standing order" })).toBeVisible();
});
