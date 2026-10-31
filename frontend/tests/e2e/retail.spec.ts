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

test("AI Innovation Lab: the overdraft assistant approves a customer overdrawn most days (its blind spot)", async ({ page }) => {
  await signIn(page, "researcher", "/ai-lab");
  const registry = page.getByRole("list", { name: "AI tools" });
  await registry.getByRole("button", { name: /AGB Overdraft Affordability Assistant/ }).click();
  const details = page.getByRole("region", { name: "Tool details" });
  await expect(details.getByRole("heading", { name: "AGB Overdraft Affordability Assistant" })).toBeVisible();
  const console = details.getByRole("form", { name: "Test console" });
  await console.getByLabel("Action").selectOption("recommend_decision");
  await console.getByRole("button", { name: "Invoke" }).click();
  await expect(console.getByRole("status")).toContainText("Recommendation: Approve");
});
