import { type Browser, expect, type Page, test } from "@playwright/test";

import { signIn, uniqueWord } from "./helpers";

async function as(browser: Browser, username: string, path: string): Promise<Page> {
  const page = await (await browser.newContext()).newPage();
  await signIn(page, username, path);
  return page;
}

/** The first option of a select whose trailing "(balance)" is above `minimum`. */
async function fundedOption(page: Page, label: string, minimum: number): Promise<string> {
  const select = page.getByRole("dialog").getByLabel(label, { exact: true });
  await expect(select.locator("option").nth(1)).toBeAttached();
  const options = await select.locator("option").evaluateAll((nodes) =>
    nodes.map((n) => ({ value: (n as HTMLOptionElement).value, text: n.textContent ?? "" })),
  );
  const funded = options.find((o) => {
    const balance = /\(([^)]*)\)\s*$/.exec(o.text)?.[1] ?? "";
    return Number(balance.replace(/[^\d.]/g, "")) > minimum;
  });
  expect(funded, "a seeded account with funds").toBeTruthy();
  return funded!.value;
}

test("WF-0002: a scam payment is held, a fraud analyst stops it and no money moves", async ({ browser }) => {
  const reference = `Gift card codes ${uniqueWord()}`;
  const amount = `${1 + Math.floor(Math.random() * 8)}.${String(10 + Math.floor(Math.random() * 90))}`;

  // A teller starts a payment whose reference carries a scam indicator.
  const teller = await as(browser, "employee", "/workflows");
  await teller.getByRole("button", { name: /Domestic Payment/ }).click();
  await teller.getByRole("button", { name: "Start a payment" }).click();
  const form = teller.getByRole("dialog");
  await form.getByLabel("Paying account", { exact: true }).selectOption(await fundedOption(teller, "Paying account", 20));
  await form.getByLabel("Payee account").selectOption({ index: 1 });
  const payee = await form.getByLabel("Payee account").inputValue();
  await form.getByLabel(/^Amount/).fill(amount);
  await form.getByLabel("Reference").fill(reference);
  await form.getByRole("button", { name: "Submit payment" }).click();

  // Screening holds it for fraud review; nothing has been posted.
  const caseView = teller.getByRole("dialog", { name: "Workflow execution" });
  await expect(caseView.getByRole("row", { name: /Fraud review of a held payment/ }).getByText("waiting")).toBeVisible();
  await expect(caseView.getByRole("row", { name: /Post the payment to the ledger/ })).toHaveCount(0);
  await teller.keyboard.press("Escape");

  // A manager cannot clear fraud holds; a compliance analyst can, and rejects it.
  const manager = await as(browser, "manager", "/workflows?tab=tasks");
  await manager.getByLabel("Only tasks I can act on").uncheck();
  await expect(manager.getByRole("listitem").filter({ hasText: "Fraud review of a held payment" }).first()).toBeVisible();
  await expect(
    manager.getByRole("listitem").filter({ hasText: "Fraud review of a held payment" }).getByRole("button", { name: /Approve/ }),
  ).toHaveCount(0);

  const analyst = await as(browser, "compliance", "/payments");
  await analyst.getByLabel("Search payments").fill(reference);
  await expect(analyst.getByRole("row").filter({ hasText: reference }).getByText("In progress")).toBeVisible();
  await analyst.goto("/workflows?tab=tasks");
  // The task names the payment: "<amount> <currency> to <payee account>".
  const task = analyst.getByRole("listitem").filter({ hasText: new RegExp(`${amount.replace(".", "\\.")} [A-Z]{3} to ${payee}`) });
  await task.getByRole("button", { name: /Reject/ }).click();
  await expect(task).toHaveCount(0);

  // The payment is rejected with the reason, and was never posted.
  await analyst.goto("/payments");
  await analyst.getByLabel("Search payments").fill(reference);
  const row = analyst.getByRole("row").filter({ hasText: reference });
  await expect(row.getByText("Rejected", { exact: true })).toBeVisible();
  await expect(row.getByText(/Declined at fraud review/)).toBeVisible();
});
