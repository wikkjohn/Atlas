import { expect, test } from "@playwright/test";

import { signIn } from "./helpers";

test("Treasury: a placement with a sub-investment-grade bank is refused; a dealer books one, back office settles it", async ({ browser, page }) => {
  await signIn(page, "employee", "/treasury");
  const form = page.getByRole("form", { name: "Book a deal" });
  await form.getByLabel("Counterparty").selectOption("CP-SAVANNA");
  await form.getByLabel("Currency").fill("GBP");
  await form.getByLabel("Principal").fill("250000");
  await form.getByLabel("Rate").fill("4.5");
  await form.getByRole("button", { name: "Book" }).click();
  await expect(form).toContainText("placements need BBB- or better");

  await form.getByLabel("Counterparty").selectOption("CP-NORTHGATE");
  const booked = page.waitForResponse((r) => r.url().endsWith("/api/v1/treasury/deals") && r.request().method() === "POST" && r.status() === 201);
  await form.getByRole("button", { name: "Book" }).click();
  const { deal_number: number } = (await (await booked).json()) as { deal_number: string };
  // The dealer cannot confirm their own deal.
  await expect(page.getByRole("button", { name: `Confirm ${number}` })).toHaveCount(0);

  const backOfficeContext = await browser.newContext();
  const backOffice = await backOfficeContext.newPage();
  await signIn(backOffice, "manager", "/treasury");
  await backOffice.getByRole("button", { name: `Confirm ${number}` }).click();
  const row = backOffice.getByRole("table", { name: "Deals" }).getByRole("row").filter({ hasText: number });
  await expect(row.getByText("settled")).toBeVisible();
  await expect(row).toContainText("£250,000.00");
  await backOfficeContext.close();
});
