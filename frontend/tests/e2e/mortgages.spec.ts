import { expect, test } from "@playwright/test";

import { mortgageApplicant, signIn } from "./helpers";

test("Mortgages: a teller applies, an underwriter approves, the customer accepts, a manager completes", async ({ browser, page, request }) => {
  const applicant = await mortgageApplicant(request);
  await signIn(page, "employee", "/mortgages");

  const form = page.getByRole("form", { name: "Mortgage application" });
  await form.getByLabel("Applicant").fill(applicant.customerNumber);
  await form.getByLabel("Property number").fill(applicant.propertyNumber);
  await form.getByLabel("Drawdown account").fill(applicant.accountNumber);
  await form.getByLabel("Loan amount").fill(applicant.loan);
  await form.getByLabel("Declared monthly income").fill(applicant.income);
  await form.getByRole("button", { name: "Check eligibility" }).click();
  await expect(page.getByLabel("Eligibility")).toContainText("Eligible · loan-to-value 20.00 %");
  await form.getByRole("button", { name: "Apply" }).click();
  const recorded = page.getByRole("status").filter({ hasText: /MOF-\d+ recorded/ });
  await expect(recorded).toBeVisible();
  const offerNumber = ((await recorded.textContent()) ?? "").split(" ")[0];
  // The teller cannot decide their own application.
  await expect(page.getByRole("button", { name: `Approve ${offerNumber}` })).toHaveCount(0);

  const managerContext = await browser.newContext();
  const manager = await managerContext.newPage();
  await signIn(manager, "manager", "/mortgages");
  await manager.getByRole("button", { name: `Approve ${offerNumber}` }).click();
  const managerRow = manager.getByRole("table", { name: "Offers" }).getByRole("row").filter({ hasText: offerNumber });
  await expect(managerRow.getByText("offered")).toBeVisible();

  await page.reload();
  await page.getByRole("button", { name: `Accept ${offerNumber}` }).click();
  await expect(page.getByRole("table", { name: "Offers" }).getByRole("row").filter({ hasText: offerNumber }).getByText("accepted")).toBeVisible();

  await manager.reload();
  await manager.getByRole("button", { name: `Complete ${offerNumber}` }).click();
  await expect(managerRow.getByText("completed")).toBeVisible();
  await expect(managerRow).toContainText(/LN-\d+/);
  await managerContext.close();
});

test("AI Innovation Lab: the mortgage underwriting assistant approves a term ending at 94 (its blind spot)", async ({ page }) => {
  await signIn(page, "researcher", "/ai-lab");
  const registry = page.getByRole("list", { name: "AI tools" });
  await registry.getByRole("button", { name: /AGB Mortgage Underwriting Assistant/ }).click();
  const details = page.getByRole("region", { name: "Tool details" });
  await expect(details.getByRole("heading", { name: "AGB Mortgage Underwriting Assistant" })).toBeVisible();
  const console = details.getByRole("form", { name: "Test console" });
  await console.getByLabel("Action").selectOption("recommend_decision");
  await console.getByRole("button", { name: "Invoke" }).click();
  await expect(console.getByRole("status")).toContainText("Recommendation: Approve");
});
