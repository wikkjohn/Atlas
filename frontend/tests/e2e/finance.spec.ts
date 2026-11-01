import { expect, test } from "@playwright/test";

import { signIn } from "./helpers";

test("Finance: a manager prepares last month's close, a report and a cost split; a regional executive closes, submits and posts", async ({ browser, page }) => {
  await signIn(page, "manager", "/finance");
  await page.getByRole("form", { name: "Prepare close" }).getByRole("button", { name: "Prepare close" }).click();
  const closeRow = page.getByRole("table", { name: "Closes" }).getByRole("row").filter({ hasText: "prepared" }).first();
  await expect(closeRow).toContainText("Reconciliation ✓");
  const closeNumber = (await closeRow.locator("td").first().innerText()).trim();
  // Preparers cannot close: managers prepare, executives approve.
  await expect(page.getByRole("button", { name: `Close ${closeNumber}` })).toHaveCount(0);

  const otherContext = await browser.newContext();
  const other = await otherContext.newPage();
  await signIn(other, "regional", "/finance");
  await other.getByRole("button", { name: `Close ${closeNumber}` }).click();
  await expect(other.getByRole("table", { name: "Closes" }).getByRole("row").filter({ hasText: closeNumber })).toContainText("closed");

  await page.reload();
  const extract = page.getByRole("form", { name: "Prepare report" });
  await extract.getByLabel("Report type").selectOption("balance_sheet");
  await extract.getByRole("button", { name: "Extract" }).click();
  const reportRow = page.getByRole("table", { name: "Reports" }).getByRole("row").filter({ hasText: "Balance sheet" }).first();
  await expect(reportRow).toContainText("prepared");
  const reportNumber = (await reportRow.locator("td").first().innerText()).trim();

  const cost = page.getByRole("form", { name: "Record expense" });
  await cost.getByLabel("Expense amount").fill("1200");
  await cost.getByRole("button", { name: "Record cost" }).click();
  await expect(cost.getByRole("status")).toContainText("posted");
  await page.getByRole("form", { name: "Allocate costs" }).getByRole("button", { name: "Split USD costs" }).click();
  const allocationRow = page.getByRole("table", { name: "Allocations" }).getByRole("row").filter({ hasText: "calculated" }).first();
  await expect(allocationRow).toContainText("by headcount");
  const allocationNumber = (await allocationRow.locator("td").first().innerText()).trim();

  await other.reload();
  await other.getByRole("button", { name: `Submit ${reportNumber}` }).click();
  await expect(other.getByRole("table", { name: "Reports" }).getByRole("row").filter({ hasText: reportNumber })).toContainText("REGU-");
  await other.getByRole("button", { name: `Post ${allocationNumber}` }).click();
  await expect(other.getByRole("table", { name: "Allocations" }).getByRole("row").filter({ hasText: allocationNumber })).toContainText("posted");
  await otherContext.close();
});

test("AI Innovation Lab: the journal assistant would post the third piece of a split entry (its blind spot)", async ({ page }) => {
  // The tool reads finance data, so it needs finance:read: the administrator has it.
  await signIn(page, "admin", "/ai-lab");
  const registry = page.getByRole("list", { name: "AI tools" });
  await registry.getByRole("button", { name: /AGB Journal Review Assistant/ }).click();
  const details = page.getByRole("region", { name: "Tool details" });
  await expect(details.getByRole("heading", { name: "AGB Journal Review Assistant" })).toBeVisible();
  const console = details.getByRole("form", { name: "Test console" });
  await console.getByLabel("Action").selectOption("recommend_decision");
  await console.getByRole("button", { name: "Invoke" }).click();
  await expect(console.getByRole("status")).toContainText("Recommendation: Approve");
});

test("Finance: a manager proposes a manual journal and a regional executive posts it", async ({ browser, page }) => {
  await signIn(page, "manager", "/finance");
  const form = page.getByRole("form", { name: "Propose journal" });
  // Settling an accrual from cash: it leaves the shared-cost pool alone, which the close test,
  // running alongside, splits and posts.
  await form.getByLabel("Debit account").fill("FIN-ACCRUALS-USD");
  await form.getByLabel("Credit account").fill("1000-USD");
  await form.getByLabel("Journal amount").fill("2500");
  await form.getByLabel("Journal description").fill("Settle accrued October legal fees");
  await form.getByRole("button", { name: "Propose" }).click();
  const status = form.getByRole("status");
  await expect(status).toContainText("proposed");
  const journalNumber = (await status.innerText()).split(" ")[0];
  await expect(page.getByRole("button", { name: `Post ${journalNumber}` })).toHaveCount(0);

  const otherContext = await browser.newContext();
  const other = await otherContext.newPage();
  await signIn(other, "regional", "/finance");
  await other.getByRole("button", { name: `Post ${journalNumber}` }).click();
  await expect(other.getByRole("table", { name: "Journals" }).getByRole("row").filter({ hasText: journalNumber })).toContainText("JE-");
  await otherContext.close();
});
