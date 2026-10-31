import { expect, test } from "@playwright/test";

import { businessAccount, signIn } from "./helpers";

test("Commercial lending: proposed, approved, drawn; a covenant breach freezes it; the committee waives", async ({ browser, page, request }) => {
  const business = await businessAccount(request);
  await signIn(page, "employee", "/commercial");

  const form = page.getByRole("form", { name: "Propose a facility" });
  await form.getByLabel("Business customer").fill(business.customerNumber);
  await form.getByLabel("Business account").fill(business.accountNumber);
  await form.getByLabel("Credit limit").fill("150000");
  const proposed = page.waitForResponse((r) => r.url().endsWith("/api/v1/commercial/facilities") && r.request().method() === "POST");
  await form.getByRole("button", { name: "Propose" }).click();
  const { facility_number: number } = (await (await proposed).json()) as { facility_number: string };
  // The teller cannot approve their own proposal.
  await expect(page.getByRole("button", { name: `Approve ${number}` })).toHaveCount(0);

  const managerContext = await browser.newContext();
  const manager = await managerContext.newPage();
  await signIn(manager, "manager", "/commercial");
  await manager.getByRole("button", { name: `Approve ${number}` }).click();
  await expect(manager.getByRole("table", { name: "Facilities" }).getByRole("row").filter({ hasText: number }).getByText("active")).toBeVisible();
  await managerContext.close();

  await page.reload();
  await page.getByRole("button", { name: `Select ${number}` }).click();
  const detail = page.getByRole("region", { name: `Facility ${number}` });
  await detail.getByLabel("Amount").fill("20000");
  await detail.getByRole("button", { name: "Draw" }).click();
  const row = page.getByRole("table", { name: "Facilities" }).getByRole("row").filter({ hasText: number });
  await expect(row).toContainText(/drawn .20,000\.00/);

  // DSCR 1.10× against 1.25×: breached, and the facility is frozen.
  const figures = detail.getByRole("form", { name: "Covenant figures" });
  await figures.getByLabel("Period end").fill("2026-06-30");
  await figures.getByLabel("EBITDA").fill("220000");
  await figures.getByLabel("Debt service").fill("200000");
  await figures.getByLabel("Total debt").fill("600000");
  await figures.getByRole("button", { name: "Test covenants" }).click();
  await expect(row.getByText("frozen")).toBeVisible();
  await expect(detail.getByRole("button", { name: "Waive 2026-06-30" })).toHaveCount(0);

  const executiveContext = await browser.newContext();
  const executive = await executiveContext.newPage();
  await signIn(executive, "executive", "/commercial");
  await executive.getByRole("button", { name: `Select ${number}` }).click();
  await executive.getByRole("region", { name: `Facility ${number}` }).getByRole("button", { name: "Waive 2026-06-30" }).click();
  await expect(executive.getByRole("table", { name: "Facilities" }).getByRole("row").filter({ hasText: number }).getByText("active")).toBeVisible();
  await executiveContext.close();
});
