import { expect, test } from "@playwright/test";

import { fundedAccount, signIn } from "./helpers";

test("Wealth: an assessed customer buys within their profile; an unsuitable order needs a manager", async ({ browser, page, request }) => {
  const investor = await fundedAccount(request, 5_000_000);
  await signIn(page, "employee", "/wealth");
  // Suitability: an income objective gives a risk profile of 3.
  const profile = page.getByRole("form", { name: "Suitability assessment" });
  await profile.getByLabel("Customer number").fill(investor.customerNumber);
  await profile.getByLabel("Objective").selectOption("income");
  await profile.getByLabel("Capacity for loss").selectOption("high");
  await profile.getByRole("button", { name: "Record profile" }).click();
  await expect(page.getByRole("status")).toContainText("Risk profile 3");

  const open = page.getByRole("form", { name: "Open a portfolio" });
  await open.getByLabel("Portfolio account").fill(investor.accountNumber);
  const opened = page.waitForResponse((r) => r.url().endsWith("/api/v1/wealth/portfolios") && r.request().method() === "POST" && r.status() === 201);
  await open.getByRole("button", { name: "Open portfolio" }).click();
  const { portfolio_number: portfolio } = (await (await opened).json()) as { portfolio_number: string };

  // A money-market fund (risk 1) is suitable: executed at once.
  const place = page.getByRole("form", { name: "Place an order" });
  await expect(place.getByLabel("Order portfolio")).toHaveValue(portfolio);
  await place.getByLabel("Security").selectOption("AGB-MMF-USD");
  await place.getByLabel("Units").fill("2");
  const bought = page.waitForResponse((r) => r.url().endsWith("/api/v1/wealth/orders") && r.request().method() === "POST" && r.status() === 201);
  await place.getByRole("button", { name: "Place order" }).click();
  const suitable = (await (await bought).json()) as { order_number: string; status: string };
  expect(suitable.status).toBe("executed");
  await expect(page.getByRole("table", { name: "Holdings" })).toContainText("AGB-MMF-USD");

  // A risk-7 complex tracker is not: it waits, and the adviser cannot approve it.
  await place.getByLabel("Security").selectOption("SN-DIGITAL-TRK");
  await place.getByLabel("Units").fill("1");
  const risky = page.waitForResponse((r) => r.url().endsWith("/api/v1/wealth/orders") && r.request().method() === "POST" && r.status() === 201);
  await place.getByRole("button", { name: "Place order" }).click();
  const { order_number: order, status } = (await (await risky).json()) as { order_number: string; status: string };
  expect(status).toBe("awaiting_approval");
  const row = page.getByRole("table", { name: "Orders" }).getByRole("row").filter({ hasText: order });
  await expect(row).toContainText("above the customer's profile of 3");
  await expect(page.getByRole("button", { name: `Approve ${order}` })).toHaveCount(0);

  const managerContext = await browser.newContext();
  const manager = await managerContext.newPage();
  await signIn(manager, "manager", "/wealth");
  await manager.getByRole("button", { name: `Approve ${order}` }).click();
  const decided = manager.getByRole("table", { name: "Orders" }).getByRole("row").filter({ hasText: order });
  await expect(decided.getByText("Executed")).toBeVisible();
  await expect(decided).toContainText("Insistent client");
  await managerContext.close();
});

test("AI Innovation Lab: the suitability assistant would let a serial insister's order go ahead (its blind spot)", async ({ page }) => {
  await signIn(page, "researcher", "/ai-lab");
  const registry = page.getByRole("list", { name: "AI tools" });
  await registry.getByRole("button", { name: /AGB Suitability Review Assistant/ }).click();
  const details = page.getByRole("region", { name: "Tool details" });
  await expect(details.getByRole("heading", { name: "AGB Suitability Review Assistant" })).toBeVisible();
  const console = details.getByRole("form", { name: "Test console" });
  await console.getByLabel("Action").selectOption("recommend_decision");
  await console.getByRole("button", { name: "Invoke" }).click();
  await expect(console.getByRole("status")).toContainText("Recommendation: Approve");
});
