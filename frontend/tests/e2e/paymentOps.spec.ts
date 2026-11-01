import { expect, test } from "@playwright/test";

import { fundedAccount, signIn } from "./helpers";

test("Payments operations: a payment to another bank clears, is recalled and comes back", async ({ browser, page, request }) => {
  const payer = await fundedAccount(request, 1_000_000);
  await signIn(page, "employee", "/payment-ops");
  const form = page.getByRole("form", { name: "Pay another bank" });
  await form.getByLabel("From account").fill(payer.accountNumber);
  await form.getByLabel("Beneficiary name").fill("Synthetic Supplier Ltd");
  await form.getByLabel("Beneficiary bank").selectOption("NBKAGB22");
  await form.getByLabel("Beneficiary account").fill("12345678901218");
  await form.getByLabel("Amount").fill("50");
  const sent = page.waitForResponse((r) => r.url().endsWith("/api/v1/payment-ops/payments") && r.request().method() === "POST" && r.status() === 201);
  await form.getByRole("button", { name: "Send" }).click();
  const { payment_number: number, currency } = (await (await sent).json()) as { payment_number: string; currency: string };
  // A teller cannot run clearing.
  await expect(page.getByRole("form", { name: "Run a clearing cycle" })).toHaveCount(0);

  const opsContext = await browser.newContext();
  const ops = await opsContext.newPage();
  await signIn(ops, "manager", "/payment-ops");
  const cycle = ops.getByRole("form", { name: "Run a clearing cycle" });
  await cycle.getByLabel("Cycle currency").fill(currency);
  await cycle.getByRole("button", { name: "Run cycle" }).click();
  const paymentRow = ops.getByRole("table", { name: "Outgoing payments" }).getByRole("row").filter({ hasText: number });
  await expect(paymentRow.getByText("Settled")).toBeVisible();

  await page.reload();
  const recallForm = page.getByRole("form", { name: "Recall a payment" });
  await recallForm.getByLabel("Payment number").fill(number);
  await recallForm.getByLabel("Reason").selectOption("TECH");
  const requested = page.waitForResponse((r) => r.url().endsWith("/api/v1/payment-ops/recalls") && r.request().method() === "POST" && r.status() === 201);
  await recallForm.getByRole("button", { name: "Request recall" }).click();
  const { recall_number: recall } = (await (await requested).json()) as { recall_number: string };
  await expect(page.getByRole("button", { name: `Approve ${recall}` })).toHaveCount(0);

  await ops.reload();
  await ops.getByRole("button", { name: `Approve ${recall}` }).click();
  await ops.getByRole("button", { name: `Record answer ${recall}` }).click();
  const recallRow = ops.getByRole("table", { name: "Recalls" }).getByRole("row").filter({ hasText: recall });
  await expect(recallRow.getByText("accepted")).toBeVisible();
  await expect(paymentRow.getByText("Recalled")).toBeVisible();
  await opsContext.close();
});
