import { type Browser, expect, type Page, test } from "@playwright/test";

import { signIn, uniqueWord } from "./helpers";

async function as(browser: Browser, username: string, path: string): Promise<Page> {
  const page = await (await browser.newContext()).newPage();
  await signIn(page, username, path);
  return page;
}

test("Multi-currency: a payment to an account in another currency is converted, then the positions are revalued", async ({ browser }) => {
  const reference = `Cross-border ${uniqueWord()}`;

  // A teller pays from a funded account to a payee whose account is in another currency.
  const teller = await as(browser, "employee", "/workflows");
  await teller.getByRole("button", { name: /Domestic Payment/ }).click();
  await teller.getByRole("button", { name: "Start a payment" }).click();
  const form = teller.getByRole("dialog");
  const paying = form.getByLabel("Paying account", { exact: true });
  await expect(paying.locator("option").nth(1)).toBeAttached();
  const payers = await paying.locator("option").evaluateAll((nodes) =>
    nodes.map((n) => ({ value: (n as HTMLOptionElement).value, text: n.textContent ?? "" })),
  );
  // A funded account (its balance has at least three digits before the decimals), any currency.
  const payer = payers.find((o) => /\(\D*\d[\d,]{2,}(\.\d+)?\)$/.test(o.text));
  expect(payer, "a funded account").toBeTruthy();
  await paying.selectOption(payer!.value);
  const amountField = form.getByLabel(/^Amount \([A-Z]{3}\)$/);
  const currency = /\(([A-Z]{3})\)/.exec((await form.locator("label", { hasText: /^Amount \(/ }).textContent()) ?? "")![1];
  const payees = await form.getByLabel("Payee account").locator("option").evaluateAll((nodes) =>
    nodes.map((n) => ({ value: (n as HTMLOptionElement).value, text: n.textContent ?? "" })),
  );
  const payee = payees.find((o) => /\(([A-Z]{3})\)$/.test(o.text) && !o.text.endsWith(`(${currency})`));
  expect(payee, `a payee in a currency other than ${currency}`).toBeTruthy();
  await form.getByLabel("Payee account").selectOption(payee!.value);
  await amountField.fill("25");
  await form.getByLabel("Reference").fill(reference);
  await expect(form.getByLabel("Conversion estimate")).toContainText("The payee receives about");
  await form.getByRole("button", { name: "Submit payment" }).click();
  const caseView = teller.getByRole("dialog", { name: "Workflow execution" });
  await expect(caseView.getByRole("row", { name: /Post the payment to the ledger/ }).getByText("completed")).toBeVisible();

  // The payment shows what the payee received and the FX deal.
  await teller.goto("/payments");
  await teller.getByLabel("Search payments").fill(reference);
  const row = teller.getByRole("row").filter({ hasText: reference });
  await expect(row.getByText("Released")).toBeVisible();
  await expect(row.getByText(/→ .*FX-\d{8}/)).toBeVisible();

  // The bank now holds open positions; an administrator revalues them.
  const admin = await as(browser, "admin", "/fx");
  const positions = admin.getByRole("region", { name: "Currency positions" });
  await expect(positions.getByRole("table", { name: "Positions" }).getByRole("row").nth(2)).toBeVisible(); // two currencies at least
  await positions.getByRole("button", { name: /^Revalue as of/ }).click();
  await expect(positions.getByLabel("Unbooked FX result")).toHaveText("$0.00");
  await expect(admin.getByRole("region", { name: "Revaluations" }).getByRole("listitem").first()).toContainText("posted");
  await expect(admin.getByRole("region", { name: "Conversions" })).toContainText(reference);
});
