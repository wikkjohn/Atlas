import { type Browser, expect, type Page, test } from "@playwright/test";

import { nav, signIn, uniqueWord } from "./helpers";

async function as(browser: Browser, username: string, path: string): Promise<Page> {
  const page = await (await browser.newContext()).newPage();
  await signIn(page, username, path);
  return page;
}

async function openCustomer(page: Page, name: string): Promise<void> {
  await page.getByRole("textbox", { name: "Search customers" }).fill(name);
  await page.getByRole("textbox", { name: "Search customers" }).press("Enter");
  await page.getByRole("row", { name: new RegExp(name) }).click();
  await expect(page.getByRole("dialog", { name: "Customer profile" })).toBeVisible();
}

test("onboard → KYC → request → four-eyes approval → deposit → reconcile", async ({ browser }) => {
  const name = `Lena ${uniqueWord().replace(/^./, (c) => c.toUpperCase())}`;

  // 1. A teller onboards a synthetic customer in Germany.
  const teller = await as(browser, "employee", "/customers");
  await teller.getByRole("button", { name: "Onboard customer" }).click();
  const onboard = teller.getByRole("dialog", { name: "Onboard customer" });
  await onboard.getByLabel("Country").selectOption({ label: "Germany" });
  await onboard.getByLabel("Full name").fill(name);
  await onboard.getByLabel("Date of birth").fill("1991-07-21");
  await onboard.getByRole("button", { name: "Onboard" }).click();
  await expect(onboard).toBeHidden();

  // The teller cannot request an account yet: KYC has not been verified.
  await openCustomer(teller, name);
  const tellerProfile = teller.getByRole("dialog", { name: "Customer profile" });
  await expect(tellerProfile.getByText(/KYC is 'not_started'/)).toBeVisible();
  await expect(tellerProfile.getByRole("button", { name: "Submit for approval" })).toBeDisabled();
  await teller.keyboard.press("Escape");

  // 2. Compliance reviews and verifies KYC with a risk rating.
  const compliance = await as(browser, "compliance", "/customers");
  await openCustomer(compliance, name);
  const review = compliance.getByRole("region", { name: "KYC review" });
  await review.getByRole("button", { name: "Start review" }).click();
  await review.getByLabel("Risk rating").selectOption("medium");
  await review.getByRole("button", { name: "Verify" }).click();
  await expect(
    compliance.getByRole("dialog", { name: "Customer profile" }).getByText("KYC verified"),
  ).toBeVisible();

  // 3. The teller requests a current account.
  await teller.reload();
  await openCustomer(teller, name);
  const request = teller.getByRole("region", { name: "Request an account" });
  await expect(request.getByRole("button", { name: "Submit for approval" })).toBeEnabled();
  await request.getByRole("button", { name: "Submit for approval" }).click();
  await expect(request.getByRole("status")).toContainText("Another authorized employee");
  await teller.keyboard.press("Escape");

  // The teller has no approval rights.
  await nav(teller).getByRole("link", { name: "Accounts" }).click();
  await teller.getByRole("tab", { name: "Opening requests" }).click();
  const tellerRow = teller.getByRole("row", { name: new RegExp(name) });
  await expect(tellerRow.getByText("Pending")).toBeVisible();
  await expect(tellerRow.getByRole("button", { name: /Approve/ })).toHaveCount(0);

  // 4. A manager approves; the account opens.
  const manager = await as(browser, "manager", "/accounts?tab=requests");
  const managerRow = manager.getByRole("row", { name: new RegExp(name) });
  await managerRow.getByRole("button", { name: /Approve/ }).click();
  await expect(managerRow).toBeHidden(); // leaves the pending list

  // 5. The teller deposits and withdraws; the balance comes from the ledger.
  await teller.getByRole("tab", { name: "Accounts" }).click();
  await teller.getByRole("textbox", { name: "Search accounts" }).fill(name);
  await teller.getByRole("textbox", { name: "Search accounts" }).press("Enter");
  await teller.getByRole("row", { name: new RegExp(name) }).click();
  const account = teller.getByRole("dialog", { name: "Account" });
  await expect(account.getByLabel("Balance")).toHaveText("€0.00");
  await account.getByLabel("Deposit (EUR)").fill("500");
  await account.getByRole("button", { name: "Deposit" }).click();
  await expect(account.getByLabel("Balance")).toHaveText("€500.00");
  await account.getByLabel("Withdraw (EUR)").fill("120.25");
  await account.getByRole("button", { name: "Withdraw" }).click();
  await expect(account.getByLabel("Balance")).toHaveText("€379.75");
  // Overdrafts are refused by the backend.
  await account.getByLabel("Withdraw (EUR)").fill("1000");
  await account.getByRole("button", { name: "Withdraw" }).click();
  await expect(account.getByRole("alert")).toContainText("Insufficient funds");
  await expect(account.getByLabel("Balance")).toHaveText("€379.75");

  // 6. An auditor reconciles the ledger in full, then incrementally; both runs are recorded.
  const auditor = await as(browser, "auditor", "/accounts?tab=ledger");
  const reconciliation = auditor.getByRole("region", { name: "Reconciliation" });
  await auditor.getByRole("button", { name: "Full reconciliation" }).click();
  await expect(reconciliation.getByText(/All checks passed · run #\d+ \(\s*full\)/)).toBeVisible();
  await expect(reconciliation.getByText("Stored balances match the lines")).toBeVisible();
  await auditor.getByRole("button", { name: "Incremental check" }).click();
  await expect(reconciliation.getByText(/All checks passed · run #\d+ \(\s*incremental\)/)).toBeVisible();
  await expect(auditor.getByRole("table", { name: "Reconciliation history" }).getByText("Incremental").first()).toBeVisible();
});
