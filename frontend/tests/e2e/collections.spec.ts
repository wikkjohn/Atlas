import { type Browser, expect, type Page, test } from "@playwright/test";

import { signIn } from "./helpers";

async function as(browser: Browser, username: string): Promise<Page> {
  const page = await (await browser.newContext()).newPage();
  await signIn(page, username, "/collections");
  return page;
}

test("Collections: a manager proposes a payment plan and a second approver activates it", async ({ browser }) => {
  // The demo seed leaves one loan two instalments in arrears.
  const manager = await as(browser, "manager");
  const arrears = manager.getByRole("table", { name: "Arrears" });
  const row = arrears.getByRole("row").filter({ hasText: "Synthetic Arrears Borrower" });
  await expect(row).toContainText("2 instalments");
  const loan = (await row.locator("td").first().innerText()).trim();
  await manager.getByLabel("Plan interval days").fill("14");
  await row.getByRole("button", { name: `Propose plan for ${loan}` }).click();
  await expect(row).toContainText("proposed");
  const plan = manager.getByRole("table", { name: "Plans" }).getByRole("row").filter({ hasText: loan });
  const planNumber = (await plan.locator("td").first().innerText()).trim();
  // The proposer cannot approve their own plan: the API refuses it.
  await plan.getByRole("button", { name: `Approve ${planNumber}` }).click();
  await expect(manager.getByText(/Four-eyes rule/)).toBeVisible();

  const admin = await as(browser, "admin");
  const adminPlan = admin.getByRole("table", { name: "Plans" }).getByRole("row").filter({ hasText: planNumber });
  await adminPlan.getByRole("button", { name: `Approve ${planNumber}` }).click();
  await expect(adminPlan).toContainText("active");
  await expect(adminPlan).toContainText("due");
});

test("Collections: a debt sale on a written-off loan waits for the credit committee", async ({ browser }) => {
  const manager = await as(browser, "manager");
  const written = manager.getByRole("table", { name: "Written-off loans" }).getByRole("row").filter({ hasText: "Synthetic Written-Off Borrower" });
  const loan = (await written.locator("td").first().innerText()).trim();
  await manager.getByLabel(`Recovery kind for ${loan}`).selectOption("debt_sale");
  await manager.getByLabel(`Recovery amount for ${loan}`).fill("1000");
  await manager.getByRole("button", { name: `Record recovery on ${loan}` }).click();
  const sale = manager.getByRole("table", { name: "Recoveries" }).getByRole("row").filter({ hasText: loan }).filter({ hasText: "Debt sale" });
  await expect(sale).toContainText("recorded");
  const recovery = (await sale.locator("td").first().innerText()).trim();
  await expect(sale.getByRole("button", { name: `Approve ${recovery}` })).toHaveCount(0);

  const regional = await as(browser, "regional");
  const pending = regional.getByRole("table", { name: "Recoveries" }).getByRole("row").filter({ hasText: recovery });
  await pending.getByRole("button", { name: `Approve ${recovery}` }).click();
  await expect(pending).toContainText("posted");
  await expect(pending).toContainText(/JE-/);
  await expect(regional.getByRole("table", { name: "Written-off loans" }).getByRole("row").filter({ hasText: loan })).toContainText(/recovered \D1,000\.00/);
});

test("AI Innovation Lab: the collections assistant would activate a plan for a borrower who broke one before (its blind spot)", async ({ page }) => {
  // The tool reads lending data (loans:read); the administrator has it.
  await signIn(page, "admin", "/ai-lab");
  const registry = page.getByRole("list", { name: "AI tools" });
  await registry.getByRole("button", { name: /AGB Collections Review Assistant/ }).click();
  const details = page.getByRole("region", { name: "Tool details" });
  await expect(details.getByRole("heading", { name: "AGB Collections Review Assistant" })).toBeVisible();
  const console = details.getByRole("form", { name: "Test console" });
  await console.getByLabel("Action").selectOption("recommend_decision");
  await console.getByRole("button", { name: "Invoke" }).click();
  await expect(console.getByRole("status")).toContainText("Recommendation: Approve");
});
