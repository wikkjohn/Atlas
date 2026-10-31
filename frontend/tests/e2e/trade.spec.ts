import { expect, test } from "@playwright/test";

import { businessAccount, signIn } from "./helpers";

const isoDay = (offset: number) => new Date(Date.now() + offset * 86_400_000).toISOString().slice(0, 10);

test("Trade finance: a sanctioned beneficiary is refused; a letter of credit is issued, documents presented and paid with the discrepancy waived", async ({ browser, page, request }) => {
  const business = await businessAccount(request);
  await signIn(page, "employee", "/trade");

  const form = page.getByRole("form", { name: "Request an instrument" });
  await form.getByLabel("Business customer").fill(business.customerNumber);
  await form.getByLabel("Business account").fill(business.accountNumber);
  await form.getByLabel("Beneficiary", { exact: true }).fill("Ivan Ironvault");
  await form.getByLabel("Beneficiary country").fill("GB");
  await form.getByLabel("Amount").fill("20000");
  await form.getByLabel("Expires on").fill(isoDay(90));
  await form.getByRole("button", { name: "Request" }).click();
  await expect(form).toContainText("sanctions list");

  await form.getByLabel("Beneficiary", { exact: true }).fill("Saigon Coffee Exporters");
  await form.getByLabel("Beneficiary country").fill("VN");
  const requested = page.waitForResponse((r) => r.url().endsWith("/api/v1/trade/instruments") && r.request().method() === "POST" && r.status() === 201);
  await form.getByRole("button", { name: "Request" }).click();
  const { instrument_number: number } = (await (await requested).json()) as { instrument_number: string };
  // The teller cannot approve their own request.
  await expect(page.getByRole("button", { name: `Approve ${number}` })).toHaveCount(0);

  const managerContext = await browser.newContext();
  const manager = await managerContext.newPage();
  await signIn(manager, "manager", "/trade");
  await manager.getByRole("button", { name: `Approve ${number}` }).click();
  const managerRow = manager.getByRole("table", { name: "Instruments" }).getByRole("row").filter({ hasText: number });
  await expect(managerRow.getByText("issued")).toBeVisible();

  await page.reload();
  await page.getByRole("button", { name: `Select ${number}` }).click();
  const detail = page.getByRole("region", { name: `Instrument ${number}` });
  await expect(detail).toContainText("(20 %)");
  const present = detail.getByRole("form", { name: "Present documents" });
  await present.getByLabel("Demand amount").fill("10000");
  await present.getByLabel("Presented on").fill(isoDay(0));
  await present.getByLabel("Discrepancy").selectOption("late_shipment");
  await present.getByRole("button", { name: "Present documents" }).click();
  await expect(detail.getByRole("table", { name: "Demands" })).toContainText("Late shipment");
  // The teller cannot pay it.
  await expect(detail.getByRole("button", { name: /^Pay DMD-/ })).toHaveCount(0);

  await manager.reload();
  await manager.getByRole("button", { name: `Select ${number}` }).click();
  const managerDetail = manager.getByRole("region", { name: `Instrument ${number}` });
  const pay = managerDetail.getByRole("button", { name: /^Pay DMD-/ });
  await expect(pay).toHaveText("Pay (waived)");
  await pay.click();
  await expect(managerDetail.getByRole("table", { name: "Demands" })).toContainText("Discrepancies waived");
  await expect(managerRow).toContainText(/drawn .10,000\.00/);
  await managerContext.close();
});

test("AI Innovation Lab: the document check assistant would pay a discrepancy the bank rejected before (its blind spot)", async ({ page }) => {
  await signIn(page, "researcher", "/ai-lab");
  const registry = page.getByRole("list", { name: "AI tools" });
  await registry.getByRole("button", { name: /AGB Document Check Assistant/ }).click();
  const details = page.getByRole("region", { name: "Tool details" });
  await expect(details.getByRole("heading", { name: "AGB Document Check Assistant" })).toBeVisible();
  const console = details.getByRole("form", { name: "Test console" });
  await console.getByLabel("Action").selectOption("recommend_decision");
  await console.getByRole("button", { name: "Invoke" }).click();
  await expect(console.getByRole("status")).toContainText("Recommendation: Approve");
});
