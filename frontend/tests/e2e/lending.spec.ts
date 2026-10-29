import { type Browser, expect, type Page, test } from "@playwright/test";

import { signIn } from "./helpers";

async function as(browser: Browser, username: string, path: string): Promise<Page> {
  const page = await (await browser.newContext()).newPage();
  await signIn(page, username, path);
  return page;
}

test("Loan servicing: a manager moves the business date, a teller pays a loan off", async ({ browser }) => {
  // A department manager runs servicing to the suggested date; it becomes the business date.
  const manager = await as(browser, "manager", "/lending");
  const businessDate = manager.getByTestId("business-date");
  await expect(businessDate).not.toHaveText("…");
  const target = await manager.getByLabel("Service to").inputValue();
  await manager.getByRole("button", { name: "Run servicing" }).click();
  await expect(businessDate).toHaveText(target);
  await expect(manager.getByRole("table", { name: "Servicing runs" }).getByRole("row").nth(1)).toContainText(target);

  // A teller cannot run servicing but can open an active loan and pay it off early.
  const teller = await as(browser, "employee", "/lending");
  await expect(teller.getByTestId("business-date")).toHaveText(target);
  await expect(teller.getByRole("button", { name: "Run servicing" })).toHaveCount(0);
  await teller.getByRole("tab", { name: "Active" }).click();
  await teller.getByRole("button", { name: /^Open LN-/ }).first().click();
  const dialog = teller.getByRole("dialog", { name: /^Loan LN-/ });
  await expect(dialog.getByRole("table", { name: "Repayment schedule" }).getByRole("row")).not.toHaveCount(0);
  await dialog.getByRole("button", { name: "Pay off early…" }).click();
  await expect(dialog.getByText(/Outstanding principal .* plus accrued interest/)).toBeVisible();
  await dialog.getByRole("button", { name: "Confirm payoff" }).click();

  // The loan is closed; every remaining instalment was settled early through the ledger.
  await expect(dialog.getByText("Repaid", { exact: true })).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Pay off early…" })).toHaveCount(0);
  await expect(dialog.getByRole("table", { name: "Repayment schedule" }).getByText("Scheduled")).toHaveCount(0);
});
