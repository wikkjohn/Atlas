import { expect, test } from "@playwright/test";

import { cardAccount, signIn } from "./helpers";

test("Cards: a teller issues a card and pays; a fraud decline blocks it; a manager releases it", async ({ browser, page, request }) => {
  const accountNumber = await cardAccount(request, 10_000);
  await signIn(page, "employee", "/cards");

  const issue = page.getByRole("form", { name: "Issue a card" });
  await issue.getByLabel("Account").fill(accountNumber);
  const issued = page.waitForResponse((r) => r.url().endsWith("/api/v1/cards") && r.request().method() === "POST");
  await issue.getByRole("button", { name: "Issue card" }).click();
  const { id, last4 } = (await (await issued).json()) as { id: string; last4: string };
  const cards = page.getByRole("table", { name: "Cards" });
  await expect(cards.getByRole("row").filter({ hasText: last4 }).getByText("active")).toBeVisible();

  // An ordinary purchase at home is approved and posted.
  const terminal = page.getByRole("form", { name: "Merchant terminal" });
  await terminal.getByLabel("Card").selectOption(id);
  await terminal.getByLabel("Amount").fill("5.00");
  await terminal.getByRole("button", { name: "Pay" }).click();
  await expect(page.getByRole("status").filter({ hasText: /AUTH-\d+: approved/ })).toBeVisible();

  // Abroad at a gambling merchant: fraud score 70, declined, and the card is blocked.
  await terminal.getByLabel("Merchant").fill("Lucky Spins");
  await terminal.getByLabel("Category").selectOption("7995");
  await terminal.getByLabel("Merchant country").fill("KY");
  await terminal.getByRole("button", { name: "Pay" }).click();
  await expect(page.getByRole("status")).toContainText("declined (fraud suspected) · fraud score 70");
  await expect(cards.getByRole("row").filter({ hasText: last4 }).getByText("blocked")).toBeVisible();
  // A teller cannot release a fraud block.
  await expect(page.getByRole("button", { name: `Release card ${last4}` })).toHaveCount(0);

  const managerContext = await browser.newContext();
  const manager = await managerContext.newPage();
  await signIn(manager, "manager", "/cards");
  await manager.getByRole("button", { name: `Release card ${last4}` }).click();
  await expect(manager.getByRole("table", { name: "Cards" }).getByRole("row").filter({ hasText: last4 }).getByText("active")).toBeVisible();
  await managerContext.close();
});
